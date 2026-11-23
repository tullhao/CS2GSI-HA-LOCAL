"""Windows-Hilfen: Adminrechte, PawnIO-Treiber und andere RGB-Programme, die stören können."""
from __future__ import annotations

import csv
import io
import logging
import os
import subprocess
import sys

from .config import PAWNIO_SETUP

log = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Programme, die RGB-Geräte exklusiv belegen. Name in der Oberfläche -> Prozessnamen (klein geschrieben)
CONFLICTS = {
    "Logitech G HUB": ["lghub.exe", "lghub_agent.exe", "lghub_system_tray.exe"],
    "Logitech Gaming Software": ["lcore.exe"],
    "Gigabyte RGB Fusion / Control Center": ["rgbfusion.exe", "gigabytecontrolcenter.exe"],
    "Corsair iCUE": ["icue.exe"],
    "ASUS Armoury Crate": ["armourycrate.exe"],
    "SignalRGB": ["signalrgb.exe"],
}


# ----------------------------------------------------------------- Adminrechte
def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin() -> bool:
    """Startet das Programm mit UAC-Abfrage neu. True, wenn der Neustart angestossen wurde."""
    if os.name != "nt":
        return False
    import ctypes
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    params = " ".join(f'"{a}"' for a in args)
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1) > 32


# ----------------------------------------------------------------- PawnIO
def pawnio_installed() -> bool:
    """PawnIO legt beim Installieren einen Windows-Treiberdienst namens 'PawnIO' an."""
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\PawnIO"):
            return True
    except OSError:
        return False


def pawnio_setup_available() -> bool:
    return PAWNIO_SETUP.exists()


def install_pawnio() -> tuple[bool, bool, str]:
    """Installiert den mitgelieferten PawnIO-Treiber still. Rückgabe: (ok, Neustart nötig, Meldung)."""
    if not pawnio_setup_available():
        return False, False, "Das PawnIO-Setup fehlt in diesem Build."
    try:
        result = subprocess.run([str(PAWNIO_SETUP), "-install", "-silent"], timeout=180,
                                creationflags=_NO_WINDOW, capture_output=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, False, f"Setup konnte nicht ausgeführt werden: {exc}"
    code = result.returncode
    log.info("PawnIO-Setup beendet mit Code %s", code)
    if code == 0:
        return True, False, "PawnIO wurde installiert."
    if code == 3010:
        return True, True, "PawnIO wurde installiert. Windows braucht einen Neustart, bis der Arbeitsspeicher erkannt wird."
    return False, False, f"PawnIO-Setup meldet Fehlercode {code}."


# ----------------------------------------------------------------- Konflikte
def running_processes() -> set[str]:
    if os.name != "nt":
        return set()
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             timeout=10, creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {row[0].lower() for row in csv.reader(io.StringIO(out)) if row}


def find_conflicts() -> dict[str, list[str]]:
    """Gefundene störende Programme: Anzeigename -> laufende Prozesse."""
    running = running_processes()
    found = {}
    for name, procs in CONFLICTS.items():
        hits = [p for p in procs if p in running]
        if hits:
            found[name] = hits
    return found


def close_processes(procs: list[str]) -> list[str]:
    """Beendet Prozesse nur für diese Sitzung. Gibt zurück, was sich nicht beenden liess."""
    failed = []
    for proc in procs:
        result = subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True,
                                timeout=15, creationflags=_NO_WINDOW)
        if result.returncode not in (0, 128):  # 128 = lief nicht (mehr)
            failed.append(proc)
    log.info("Beendet: %s, fehlgeschlagen: %s", procs, failed)
    return failed
