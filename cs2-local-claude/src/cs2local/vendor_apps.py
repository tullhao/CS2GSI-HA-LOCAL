"""Hersteller-RGB-Software (GCC, iCUE, G HUB …) für die Sitzung pausieren und beim Beenden wieder starten.

Erkannt wird über den Installationsordner, nicht über Prozessnamen. Das findet auch Hintergrunddienste und
überlebt Updates, bei denen Hersteller ihre Programme umbenennen. Gestoppt werden Windows-Dienste sauber
(Stop-Service) und Programme per Prozess-ID. Für den Neustart merkt sich das Tool die genaue Befehlszeile.
Die Liste wird zusätzlich in einer Datei gesichert, damit ein Absturz nichts verliert.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

from .config import app_dir

log = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
PENDING_FILE = app_dir() / "cs2local_restart.json"

# Anzeigename -> Teile des Installationspfads (klein geschrieben)
VENDORS = {
    "Gigabyte Control Center / RGB Fusion": ["\\gigabyte\\"],
    "Corsair iCUE": ["\\corsair\\"],
    "Logitech G HUB": ["\\lghub\\", "\\logitech gaming software\\"],
    "ASUS Armoury Crate / Aura": ["\\asus\\armourycrate", "\\asus\\aura", "\\armoury crate", "\\asus\\asusframework"],
    "MSI Center / Mystic Light": ["\\msi\\one dragon center", "\\msi\\msi center", "\\mystic_light", "\\msi\\mystic"],
    "Razer Synapse / Chroma": ["\\razer\\synapse", "\\razer\\chroma", "\\razer chroma"],
    "NZXT CAM": ["\\nzxt cam\\"],
    "SignalRGB": ["\\signalrgb\\", "\\whirlwindfx\\"],
    "Alphacool": ["\\alphacool\\"],
}


def _powershell(script: str, timeout: int = 30) -> str:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                            capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)
    return result.stdout


def _vendor_of(path: str | None) -> str | None:
    p = (path or "").lower().replace("/", "\\")
    for name, parts in VENDORS.items():
        if any(part in p for part in parts):
            return name
    return None


def scan() -> dict:
    """Laufende Hersteller-Software: {Anzeigename: {"services": [...], "processes": [...]}}."""
    if os.name != "nt":
        return {}
    script = (
        "$p = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath } | "
        "Select-Object ProcessId, Name, ExecutablePath, CommandLine; "
        "$s = Get-CimInstance Win32_Service | Where-Object { $_.State -eq 'Running' } | "
        "Select-Object Name, DisplayName, PathName, ProcessId, StartMode; "
        "@{processes=@($p); services=@($s)} | ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        data = json.loads(_powershell(script) or "{}")
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Prozessliste nicht lesbar: %s", exc)
        return {}
    own = os.getpid()
    found: dict = {}
    service_pids = set()
    for svc in data.get("services") or []:
        vendor = _vendor_of(svc.get("PathName"))
        if vendor:
            found.setdefault(vendor, {"services": [], "processes": []})["services"].append(
                {"name": svc["Name"], "display": svc.get("DisplayName") or svc["Name"]})
            service_pids.add(svc.get("ProcessId"))
    for proc in data.get("processes") or []:
        vendor = _vendor_of(proc.get("ExecutablePath"))
        if not vendor or proc.get("ProcessId") in (own, *service_pids):
            continue
        found.setdefault(vendor, {"services": [], "processes": []})["processes"].append({
            "pid": proc["ProcessId"], "name": proc.get("Name"), "path": proc["ExecutablePath"],
            "cmd": proc.get("CommandLine") or f'"{proc["ExecutablePath"]}"'})
    log.info("Hersteller-Software gefunden: %s", {k: (len(v["services"]), len(v["processes"])) for k, v in found.items()})
    return found


def pause(found: dict) -> list:
    """Stoppt Dienste und beendet Programme. Gibt zurück, was sich nicht stoppen liess."""
    failed = []
    restart = {"services": [], "processes": []}
    for vendor, items in found.items():
        for svc in items["services"]:
            out = _powershell(f"try {{ Stop-Service -Name '{svc['name']}' -Force -ErrorAction Stop; 'ok' }} "
                              f"catch {{ $_.Exception.Message }}")
            if out.strip() == "ok":
                restart["services"].append(svc["name"])
            else:
                failed.append(f"{svc['display']} ({out.strip()[:80]})")
        seen = set()
        for proc in items["processes"]:
            result = subprocess.run(["taskkill", "/F", "/PID", str(proc["pid"])], capture_output=True,
                                    timeout=15, creationflags=_NO_WINDOW)
            if result.returncode in (0, 128):
                if proc["cmd"] not in seen:
                    restart["processes"].append({"cmd": proc["cmd"], "path": proc["path"], "vendor": vendor})
                    seen.add(proc["cmd"])
            else:
                failed.append(proc["name"])
    _save_pending(restart)
    log.info("Pausiert: %d Dienste, %d Programme, Fehler: %s", len(restart["services"]),
             len(restart["processes"]), failed)
    return failed


def _save_pending(restart: dict) -> None:
    old = load_pending()
    merged = {"services": list(dict.fromkeys(old["services"] + restart["services"])),
              "processes": old["processes"] + [p for p in restart["processes"]
                                               if p["cmd"] not in {q["cmd"] for q in old["processes"]}]}
    try:
        PENDING_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        log.warning("Neustart-Liste nicht speicherbar")


def load_pending() -> dict:
    try:
        data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        return {"services": list(data.get("services", [])), "processes": list(data.get("processes", []))}
    except (OSError, ValueError):
        return {"services": [], "processes": []}


def resume() -> list:
    """Startet alles wieder, was das Tool pausiert hat. Gibt Fehler zurück."""
    pending = load_pending()
    errors = []
    for name in pending["services"]:
        out = _powershell(f"try {{ Start-Service -Name '{name}' -ErrorAction Stop; 'ok' }} catch {{ $_.Exception.Message }}")
        if out.strip() != "ok":
            errors.append(f"Dienst {name}: {out.strip()[:80]}")
    if pending["services"]:
        time.sleep(3.0)  # Dienste starten ihre Programme oft selbst
    running = {(p.get("ExecutablePath") or "").lower() for p in _running_paths()}
    for proc in pending["processes"]:
        if proc["path"].lower() in running:  # schon wieder da (z. B. vom Dienst gestartet)
            continue
        try:
            subprocess.Popen(proc["cmd"], cwd=str(Path(proc["path"]).parent), creationflags=_DETACHED,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             close_fds=True)
        except OSError as exc:
            errors.append(f"{Path(proc['path']).name}: {exc}")
    try:
        PENDING_FILE.unlink()
    except OSError:
        pass
    log.info("Wieder gestartet: %d Dienste, %d Programme, Fehler: %s",
             len(pending["services"]), len(pending["processes"]), errors)
    return errors


def _running_paths() -> list:
    if os.name != "nt":
        return []
    try:
        data = json.loads(_powershell("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath } | "
                                      "Select-Object ExecutablePath | ConvertTo-Json -Compress") or "[]")
        return data if isinstance(data, list) else [data]
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return []
