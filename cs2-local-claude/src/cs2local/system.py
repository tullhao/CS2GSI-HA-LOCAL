"""Windows-Hilfen: Adminrechte, PawnIO-Treiber und andere RGB-Programme, die stören können."""
from __future__ import annotations

import logging
import os
import subprocess
import sys

from .config import PAWNIO_SETUP
from .i18n import tr

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
        return False, False, tr("Das PawnIO-Setup fehlt in diesem Build.")
    try:
        result = subprocess.run([str(PAWNIO_SETUP), "-install", "-silent"], timeout=180,
                                creationflags=_NO_WINDOW, capture_output=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, False, tr("Setup konnte nicht ausgeführt werden: {v0}", v0=exc)
    code = result.returncode
    log.info("PawnIO-Setup beendet mit Code %s", code)
    if code == 0:
        return True, False, tr("PawnIO wurde installiert.")
    if code == 3010:
        return True, True, tr("PawnIO wurde installiert. Windows braucht einen Neustart, bis der Arbeitsspeicher erkannt wird.")
    return False, False, tr("PawnIO-Setup meldet Fehlercode {v0}.", v0=code)


# --- Autostart -------------------------------------------------------------------------------------------
# Die EXE verlangt Adminrechte. Programme mit Adminrechten startet Windows aus dem normalen Autostart
# (Registry "Run") stillschweigend nicht. Deshalb eine Aufgabe in der Aufgabenplanung: bei Anmeldung,
# mit höchsten Rechten. Nur auf ausdrücklichen Wunsch, nie automatisch.
AUTOSTART_TASK = "CS2 Local Claude"


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, timeout=20,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def autostart_supported() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        return _schtasks("/Query", "/TN", AUTOSTART_TASK).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def set_autostart(enabled: bool) -> tuple[bool, str]:
    """Schaltet den Autostart ein oder aus. Rückgabe: (ok, Fehlermeldung)."""
    if not autostart_supported():
        return False, tr("Autostart gibt es nur für die fertige EXE unter Windows.")
    try:
        if enabled:
            cmd = f'"{sys.executable}" --autostart'
            r = _schtasks("/Create", "/TN", AUTOSTART_TASK, "/TR", cmd, "/SC", "ONLOGON", "/RL", "HIGHEST", "/F")
        else:
            r = _schtasks("/Delete", "/TN", AUTOSTART_TASK, "/F")
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if r.returncode != 0:
        log.warning("Autostart %s fehlgeschlagen: %s", "an" if enabled else "aus", (r.stderr or r.stdout).strip())
        return False, (r.stderr or r.stdout).strip()
    log.info("Autostart %s (%s)", "eingeschaltet" if enabled else "ausgeschaltet", sys.executable)
    return True, ""
