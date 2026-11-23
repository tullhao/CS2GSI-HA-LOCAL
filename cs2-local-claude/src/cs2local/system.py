"""Windows-Hilfen: Adminrechte, PawnIO-Treiber und andere RGB-Programme, die stören können."""
from __future__ import annotations

import logging
import os
import subprocess
import sys

from .config import PAWNIO_SETUP

log = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

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
