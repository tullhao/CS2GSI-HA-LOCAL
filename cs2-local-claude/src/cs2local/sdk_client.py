"""Schlanker, robuster Client für das OpenRGB-SDK-Protokoll (Version 4).

Warum eigener Client: Die Python-Bibliothek openrgb-python liest Antworten nur nebenbei, schaltet Modi mit
einer Wettlaufsituation um und gibt die Verbindung beim ersten Hänger endgültig auf. Hier läuft ein eigener
Lese-Thread, der jedes Paket des Servers sofort abholt. LED-Updates werden nur gesendet, nie beantwortet.
Bricht die Verbindung ab, meldet der Client das sauber und der Aufrufer kann neu verbinden.

Datenformat nach OpenRGB: NetworkProtocol.h, NetworkServer.cpp, RGBController.cpp (GetDeviceDescriptionData).
"""
from __future__ import annotations

import logging
import queue
import socket
import struct
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MAGIC = b"ORGB"
HEADER = struct.Struct("<4sIII")  # Magic, Geräte-ID, Paket-ID, Datenlänge
CLIENT_PROTOCOL = 4

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
DEVICE_LIST_UPDATED = 100
RESIZE_ZONE = 1000
UPDATE_ZONE_LEDS = 1051
SET_CUSTOM_MODE = 1100
UPDATE_MODE = 1101

COLOR_MODE_PER_LED = 1
COLOR_MODE_SPECIFIC = 2

DEVICE_TYPES = {
    0: "Mainboard", 1: "Arbeitsspeicher", 2: "Grafikkarte", 3: "Kühlung", 4: "LED-Streifen", 5: "Tastatur",
    6: "Maus", 7: "Mauspad", 8: "Headset", 9: "Headset-Ständer", 10: "Gamepad", 11: "Licht", 12: "Lautsprecher",
    13: "Virtuell", 14: "Speicher", 15: "Gehäuse", 16: "Mikrofon", 17: "Zubehör", 18: "Tastenfeld", 19: "Laptop",
    20: "Monitor",
}


class SDKError(ConnectionError):
    """Verbindung zur RGB-Engine verloren oder keine Antwort."""


# ---------------------------------------------------------------------------------------------- Datenmodell
@dataclass
class Mode:
    index: int
    name: str
    color_mode: int
    raw: bytes  # Moduseintrag exakt wie empfangen, für UPDATE_MODE unverändert zurückgeschickt
    num_colors: int = 0

    def with_color(self, rgb) -> "Mode":
        """Gleicher Modus, aber alle Modusfarben auf rgb gesetzt (für Geräte ohne Direktsteuerung)."""
        n = max(1, self.num_colors)
        head = self.raw[:len(self.raw) - (2 + 4 * self.num_colors)]
        raw = head + struct.pack("<H", n) + pack_color(rgb) * n
        return Mode(self.index, self.name, self.color_mode, raw, n)


@dataclass
class Zone:
    index: int
    name: str
    type: int
    leds_min: int
    leds_max: int
    leds_count: int
    start: int  # Position der ersten LED dieser Zone in der Farbliste des Geräts


@dataclass
class Device:
    index: int
    name: str
    type: int
    vendor: str
    active_mode: int
    modes: list = field(default_factory=list)
    zones: list = field(default_factory=list)
    colors: list = field(default_factory=list)  # 0x00BBGGRR

    @property
    def type_name(self) -> str:
        return DEVICE_TYPES.get(self.type, "Gerät")

    def zone_colors(self, zone: Zone) -> list:
        return self.colors[zone.start:zone.start + zone.leds_count]

    def static_mode(self) -> Mode | None:
        """Ein Modus mit einer frei wählbaren Farbe (meist „Static“), als zweite Methode."""
        candidates = [m for m in self.modes if m.color_mode == COLOR_MODE_SPECIFIC and m.num_colors >= 1]
        for m in candidates:
            if m.name.strip().lower() in ("static", "statisch", "fixed"):
                return m
        return candidates[0] if candidates else None

    def mode_by_name(self, name: str) -> Mode | None:
        for mode in self.modes:
            if mode.name.strip().lower() == name.lower():
                return mode
        return None


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ValueError("Gerätedaten zu kurz")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def string(self) -> str:
        length = self.u16()
        return self.take(length).split(b"\0", 1)[0].decode("utf-8", errors="replace")


def parse_device(index: int, body: bytes, version: int) -> Device:
    """Liest eine Gerätebeschreibung (Antwort auf REQUEST_CONTROLLER_DATA) für Protokoll 0 bis 4."""
    r = _Reader(body)
    r.u32()  # Gesamtgrösse
    dev_type = r.i32()
    name = r.string()
    vendor = r.string() if version >= 1 else ""
    r.string()  # Beschreibung
    r.string()  # Version
    r.string()  # Seriennummer
    r.string()  # Ort
    num_modes = r.u16()
    active_mode = r.i32()
    modes = []
    for i in range(num_modes):
        start = r.pos
        mode_name = r.string()
        r.i32()           # value
        r.u32()           # flags
        r.u32(); r.u32()  # speed min/max
        if version >= 3:
            r.u32(); r.u32()  # brightness min/max
        r.u32(); r.u32()  # colors min/max
        r.u32()           # speed
        if version >= 3:
            r.u32()       # brightness
        r.u32()           # direction
        color_mode = r.u32()
        num_colors = r.u16()
        r.take(4 * num_colors)  # Modusfarben
        modes.append(Mode(i, mode_name, color_mode, body[start:r.pos], num_colors))
    num_zones = r.u16()
    zones = []
    led_start = 0
    for i in range(num_zones):
        zone_name = r.string()
        zone_type = r.u32()
        leds_min, leds_max, leds_count = r.u32(), r.u32(), r.u32()
        r.take(r.u16())  # Matrix-Karte
        if version >= 4:
            for _ in range(r.u16()):  # Segmente
                r.string(); r.u32(); r.u32(); r.u32()
        zones.append(Zone(i, zone_name, zone_type, leds_min, leds_max, leds_count, led_start))
        led_start += leds_count
    for _ in range(r.u16()):  # LEDs
        r.string(); r.u32()
    colors = [r.u32() for _ in range(r.u16())]
    return Device(index, name, dev_type, vendor, active_mode, modes, zones, colors)


def pack_color(c) -> bytes:
    return struct.pack("<I", (int(c[0]) & 255) | ((int(c[1]) & 255) << 8) | ((int(c[2]) & 255) << 16))


# ---------------------------------------------------------------------------------------------- Verbindung
class SDKClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 6742, name: str = "CS2 Local Claude",
                 timeout: float = 8.0):
        self.host, self.port, self.name, self.timeout = host, port, name, timeout
        self.version = 0
        self.list_changed = False
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._replies: queue.Queue = queue.Queue()
        self._alive = False

    # ---------------------------------------------------------------- Aufbau/Abbau
    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=3.0)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(1.0)
        self._sock = sock
        self._alive = True
        threading.Thread(target=self._read_loop, name="sdk-reader", daemon=True).start()
        try:
            body = self._request(0, REQUEST_PROTOCOL_VERSION, struct.pack("<I", CLIENT_PROTOCOL),
                                 REQUEST_PROTOCOL_VERSION, timeout=2.0)
            server = struct.unpack("<I", body[:4])[0]
        except SDKError:
            if not self._alive:
                raise
            server = 0  # sehr alte Server antworten nicht
        self.version = min(server, CLIENT_PROTOCOL)
        self._send(0, SET_CLIENT_NAME, self.name.encode("utf-8") + b"\0")
        log.info("SDK verbunden, Protokoll %s (Server %s)", self.version, server)

    @property
    def alive(self) -> bool:
        return self._alive

    def close(self) -> None:
        self._alive = False
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

    # ---------------------------------------------------------------- Transport
    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            if not self._alive or self._sock is None:
                raise SDKError("Verbindung geschlossen")
            try:
                chunk = self._sock.recv(n - len(buf))
            except socket.timeout:
                continue
            except OSError as exc:
                raise SDKError(str(exc)) from exc
            if not chunk:
                raise SDKError("Die RGB-Engine hat die Verbindung beendet")
            buf += chunk
        return bytes(buf)

    def _read_loop(self) -> None:
        try:
            while self._alive:
                magic, dev_id, pkt_id, size = HEADER.unpack(self._recv_exact(HEADER.size))
                if magic != MAGIC:
                    raise SDKError("Ungültige Daten von der RGB-Engine")
                body = self._recv_exact(size) if size else b""
                if pkt_id == DEVICE_LIST_UPDATED:
                    self.list_changed = True
                else:
                    self._replies.put((pkt_id, dev_id, body))
        except SDKError as exc:
            if self._alive:
                log.warning("SDK-Verbindung getrennt: %s", exc)
        finally:
            self._alive = False
            self._replies.put(None)

    def _send(self, dev_id: int, pkt_id: int, payload: bytes = b"") -> None:
        if not self._alive or self._sock is None:
            raise SDKError("Nicht verbunden")
        data = HEADER.pack(MAGIC, dev_id, pkt_id, len(payload)) + payload
        with self._send_lock:
            try:
                self._sock.settimeout(self.timeout)
                self._sock.sendall(data)
            except OSError as exc:
                self._alive = False
                raise SDKError(f"Senden fehlgeschlagen: {exc}") from exc
            finally:
                if self._sock:
                    self._sock.settimeout(1.0)

    def _request(self, dev_id: int, pkt_id: int, payload: bytes, reply_id: int, timeout: float | None = None) -> bytes:
        with self._request_lock:
            while True:  # alte, unabgeholte Antworten verwerfen
                try:
                    if self._replies.get_nowait() is None:
                        self._replies.put(None)
                        break
                except queue.Empty:
                    break
            self._send(dev_id, pkt_id, payload)
            wait = timeout or self.timeout
            while True:
                try:
                    item = self._replies.get(timeout=wait)
                except queue.Empty:
                    raise SDKError(f"Keine Antwort der RGB-Engine (Paket {pkt_id})") from None
                if item is None:
                    self._replies.put(None)
                    raise SDKError("Verbindung während einer Anfrage getrennt")
                if item[0] == reply_id and item[1] == dev_id:
                    return item[2]

    # ---------------------------------------------------------------- Anfragen
    def controller_count(self) -> int:
        body = self._request(0, REQUEST_CONTROLLER_COUNT, b"", REQUEST_CONTROLLER_COUNT)
        return struct.unpack("<I", body[:4])[0]

    def device(self, index: int) -> Device:
        payload = struct.pack("<I", self.version) if self.version >= 1 else b""
        body = self._request(index, REQUEST_CONTROLLER_DATA, payload, REQUEST_CONTROLLER_DATA)
        return parse_device(index, body, self.version)

    def devices(self) -> list:
        self.list_changed = False
        return [self.device(i) for i in range(self.controller_count())]

    # ---------------------------------------------------------------- Befehle (ohne Antwort)
    def update_zone_leds(self, dev_index: int, zone_index: int, colors) -> None:
        packed = b"".join(pack_color(c) for c in colors)
        size = 4 + 4 + 2 + len(packed)
        self._send(dev_index, UPDATE_ZONE_LEDS, struct.pack("<IIH", size, zone_index, len(colors)) + packed)

    def update_zone_raw(self, dev_index: int, zone_index: int, raw_colors) -> None:
        packed = b"".join(struct.pack("<I", c) for c in raw_colors)
        size = 4 + 4 + 2 + len(packed)
        self._send(dev_index, UPDATE_ZONE_LEDS, struct.pack("<IIH", size, zone_index, len(raw_colors)) + packed)

    def update_mode(self, dev_index: int, mode: Mode) -> None:
        self._send(dev_index, UPDATE_MODE, struct.pack("<Ii", 8 + len(mode.raw), mode.index) + mode.raw)

    def set_custom_mode(self, dev_index: int) -> None:
        self._send(dev_index, SET_CUSTOM_MODE)

    def resize_zone(self, dev_index: int, zone_index: int, size: int) -> None:
        self._send(dev_index, RESIZE_ZONE, struct.pack("<ii", zone_index, size))
