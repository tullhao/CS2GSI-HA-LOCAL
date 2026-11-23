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


# --- Windows „Dynamische Beleuchtung“ ---------------------------------------------------------------------
# Windows 11 kann RGB-Geräte über „Lamp Array“ selbst steuern. Solange das an ist, ignorieren manche Controller
# (z. B. Gigabyte IT5711 auf X870-Boards) jeden anderen Befehl. Schalter: HKCU\Software\Microsoft\Lighting,
# Wert AmbientLightingEnabled (1 oder fehlt = an, 0 = aus) – derselbe Wert, den die Windows-Einstellungen setzen.
_LIGHTING_KEY = r"Software\Microsoft\Lighting"
_LIGHTING_VALUE = "AmbientLightingEnabled"


def dynamic_lighting_enabled() -> bool | None:
    """True/False unter Windows, None, wenn es die Einstellung hier nicht gibt (kein Windows)."""
    if os.name != "nt":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _LIGHTING_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _LIGHTING_VALUE)
            return bool(value)
    except FileNotFoundError:
        return True  # nie geändert: Windows-Standard ist „an“
    except OSError as exc:
        log.warning("Dynamische Beleuchtung nicht lesbar: %s", exc)
        return None


def set_dynamic_lighting(enabled: bool) -> bool:
    """Schaltet die Dynamische Beleuchtung von Windows an oder aus. Rückgabe: ok."""
    if os.name != "nt":
        return False
    import ctypes
    import winreg
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _LIGHTING_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _LIGHTING_VALUE, 0, winreg.REG_DWORD, 1 if enabled else 0)
    except OSError as exc:
        log.warning("Dynamische Beleuchtung nicht änderbar: %s", exc)
        return False
    try:  # Windows über die geänderte Einstellung informieren (wie die Einstellungen-App)
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Lighting", 0x0002, 2000, ctypes.byref(result))
    except Exception:  # noqa: BLE001
        pass
    log.info("Windows-Dynamische Beleuchtung %s", "eingeschaltet" if enabled else "ausgeschaltet")
    return True
