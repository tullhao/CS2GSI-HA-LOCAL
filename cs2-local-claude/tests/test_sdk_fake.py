"""Testet den SDK-Client gegen einen nachgebauten Server, der das Format wie OpenRGB (RGBController.cpp) schreibt.

Läuft überall (ohne Windows): python tests/test_sdk_fake.py
"""
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2local.sdk_client import (  # noqa: E402
    DEVICE_LIST_UPDATED, HEADER, MAGIC, REQUEST_CONTROLLER_COUNT, REQUEST_CONTROLLER_DATA, REQUEST_PROTOCOL_VERSION,
    RESIZE_ZONE, SET_CLIENT_NAME, SET_CUSTOM_MODE, UPDATE_MODE, UPDATE_ZONE_LEDS, SDKClient, SDKError,
)


def s(text: str) -> bytes:
    raw = text.encode() + b"\0"
    return struct.pack("<H", len(raw)) + raw


def mode(name: str, color_mode: int, colors=()) -> bytes:
    return (s(name) + struct.pack("<iI", 0, 0) + struct.pack("<II", 0, 0) + struct.pack("<II", 0, 100)
            + struct.pack("<II", 0, 0) + struct.pack("<I", 0) + struct.pack("<I", 100) + struct.pack("<I", 0)
            + struct.pack("<I", color_mode) + struct.pack("<H", len(colors)) + b"".join(struct.pack("<I", c) for c in colors))


class FakeDevice:
    def __init__(self, name, zones, modes):
        self.name, self.zones, self.modes = name, zones, modes  # zones: [name, min, max, count]
        self.active = 0
        self.colors = [0] * sum(z[3] for z in zones)

    def describe(self) -> bytes:
        body = struct.pack("<i", 5) + s(self.name) + s("Vendor") + s("Desc") + s("1.0") + s("SN") + s("USB")
        body += struct.pack("<H", len(self.modes)) + struct.pack("<i", self.active)
        body += b"".join(mode(n, cm, [0xFF]) for n, cm in self.modes)
        body += struct.pack("<H", len(self.zones))
        for name, lo, hi, count in self.zones:
            matrix = struct.pack("<II", 1, 2) + struct.pack("<II", 0, 1)
            body += s(name) + struct.pack("<I", 1) + struct.pack("<III", lo, hi, count)
            body += struct.pack("<H", len(matrix)) + matrix
            body += struct.pack("<H", 1) + s("Seg") + struct.pack("<III", 0, 0, count)
        body += struct.pack("<H", len(self.colors))
        body += b"".join(s(f"LED {i}") + struct.pack("<I", i) for i in range(len(self.colors)))
        body += struct.pack("<H", len(self.colors)) + b"".join(struct.pack("<I", c) for c in self.colors)
        return struct.pack("<I", len(body) + 4) + body


class FakeServer:
    def __init__(self):
        self.devices = [
            FakeDevice("Board", [["ARGB 1", 0, 300, 0], ["Logo", 1, 1, 1]], [("Static", 2), ("Direct", 1)]),
            FakeDevice("Keyboard", [["Keys", 92, 92, 92]], [("Wave", 0), ("Custom", 1)]),
        ]
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.received = []
        self.conns = []
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.conns.append(conn)
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    @staticmethod
    def recv(conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError
            buf += chunk
        return buf

    def reply(self, conn, dev, pkt, body):
        conn.sendall(HEADER.pack(MAGIC, dev, pkt, len(body)) + body)

    def serve(self, conn):
        try:
            while True:
                magic, dev, pkt, size = HEADER.unpack(self.recv(conn, 16))
                body = self.recv(conn, size) if size else b""
                self.received.append(pkt)
                if pkt == REQUEST_PROTOCOL_VERSION:
                    self.reply(conn, 0, pkt, struct.pack("<I", 6))
                elif pkt == REQUEST_CONTROLLER_COUNT:
                    self.reply(conn, 0, DEVICE_LIST_UPDATED, b"")  # unaufgeforderte Meldung dazwischen
                    self.reply(conn, 0, pkt, struct.pack("<I", len(self.devices)))
                elif pkt == REQUEST_CONTROLLER_DATA:
                    assert struct.unpack("<I", body)[0] == 4
                    self.reply(conn, dev, pkt, self.devices[dev].describe())
                elif pkt == UPDATE_ZONE_LEDS:
                    size_pkt, zone, n = struct.unpack("<IIH", body[:10])
                    assert size_pkt == len(body), (size_pkt, len(body))
                    d = self.devices[dev]
                    start = sum(z[3] for z in d.zones[:zone])
                    d.colors[start:start + n] = list(struct.unpack(f"<{n}I", body[10:]))
                elif pkt == UPDATE_MODE:
                    size_pkt, idx = struct.unpack("<Ii", body[:8])
                    assert size_pkt == len(body)
                    self.devices[dev].active = idx
                    self.last_mode = body
                elif pkt == SET_CUSTOM_MODE:
                    self.devices[dev].active = len(self.devices[dev].modes) - 1
                elif pkt == RESIZE_ZONE:
                    zone, new = struct.unpack("<ii", body)
                    z = self.devices[dev].zones[zone]
                    z[3] = new
                    self.devices[dev].colors = [0] * sum(z[3] for z in self.devices[dev].zones)
                elif pkt == SET_CLIENT_NAME:
                    assert body.endswith(b"\0")
        except (ConnectionError, OSError):
            pass

    def drop_clients(self):
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass


srv = FakeServer()
client = SDKClient("127.0.0.1", srv.port)
client.connect()
assert client.version == 4
devs = client.devices()
assert [d.name for d in devs] == ["Board", "Keyboard"]
board, kb = devs
assert board.vendor == "Vendor" and [m.name for m in board.modes] == ["Static", "Direct"]
assert [(z.name, z.leds_min, z.leds_max, z.leds_count) for z in board.zones] == [("ARGB 1", 0, 300, 0), ("Logo", 1, 1, 1)]
assert board.zones[1].start == 0 and kb.zones[0].leds_count == 92
assert client.list_changed  # DEVICE_LIST_UPDATED wurde im Hintergrund erkannt
print("Gerätedaten korrekt gelesen")

client.update_mode(board.index, board.mode_by_name("Direct"))
client.resize_zone(board.index, 0, 30)
client.update_zone_leds(kb.index, 0, [(255, 0, 16)] * 92)
time.sleep(0.2)
board = client.device(0)
assert board.active_mode == 1 and board.zones[0].leds_count == 30
assert client.device(1).colors[0] == 0x1000FF
print("Modus, Zonengrösse und Farben kommen an")

# Viele schnelle Updates aus mehreren Threads plus Abfragen
def spam():
    for i in range(300):
        client.update_zone_leds(1, 0, [(i % 256, 0, 0)] * 92)


threads = [threading.Thread(target=spam) for _ in range(3)]
for t in threads:
    t.start()
for _ in range(20):
    assert client.device(0).name == "Board"
for t in threads:
    t.join()
print("Dauerlast mit parallelen Abfragen ok")

srv.drop_clients()
time.sleep(0.3)
assert not client.alive
try:
    client.update_zone_leds(1, 0, [(0, 0, 0)] * 92)
    raise AssertionError("Abriss nicht erkannt")
except SDKError:
    pass
client2 = SDKClient("127.0.0.1", srv.port)
client2.connect()
assert client2.controller_count() == 2
print("Abriss erkannt, Neuverbindung ok")
# Zweite Methode (Static-Modus) über die Engine
from cs2local.rgb_engine import RGBEngine  # noqa: E402
from cs2local.sdk_client import pack_color  # noqa: E402

eng = RGBEngine(srv.port)
eng.client = client2
eng._load_devices()  # noqa: SLF001
assert eng.has_static("Board::Logo") and eng.device_key("Board::Logo") == "Board"
eng.methods = {"Board": "static"}
eng.prepare(["Board::Logo"])
eng.set_zone("Board::Logo", [(10, 20, 30)])
time.sleep(0.2)
assert client2.device(0).active_mode == 0, "Static-Modus nicht gesetzt"
assert srv.last_mode.endswith(pack_color((10, 20, 30))), "Farbe nicht im Static-Modus"
eng.restore()
print("Static-Methode ok")
print("SDK-CLIENT OK")
