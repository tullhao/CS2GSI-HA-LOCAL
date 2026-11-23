"""Hersteller-RGB-Software erkennen, für die Sitzung pausieren und beim Beenden wieder starten.

Erkennung (robust, unabhängig von Prozessnamen):
  - installiert: Windows-Deinstallationsliste und Microsoft-Store-Apps (Name, Herausgeber, Ordner)
  - laufend: Programme (Pfad, Firmenname in der Datei, Produktname) und Windows-Dienste
Pausieren: Dienste mit Stop-Service, Programme per Prozess-ID. Für den Neustart merkt sich das Tool die genaue
Befehlszeile bzw. bei Store-Apps die App-ID. Die Liste liegt zusätzlich in einer Datei (Absturzschutz).
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

# Katalog: Anzeigename -> Suchbegriffe (klein, in Pfad, Firma, Produkt, Herausgeber oder Dienstname)
CATALOG = {
    "Gigabyte Control Center / RGB Fusion": ["gigabyte", "aorus", "rgbfusion", "rgb fusion", "gcc.exe"],
    "ASUS Armoury Crate / Aura Sync": ["armoury crate", "armourycrate", "aura sync", "lightingservice", "asus\\aura",
                                       "asusframework", "asus com service", "romg"],
    "MSI Center / Mystic Light": ["msi center", "mystic light", "mysticlight", "dragon center", "msi.centralserver",
                                  "msi\\one dragon", "micro-star"],
    "ASRock Polychrome": ["polychrome", "asrock rgb", "asrledservice"],
    "Corsair iCUE": ["icue", "corsair"],
    "Logitech G HUB": ["lghub", "g hub", "logitech gaming software", "lcore.exe"],
    "Razer Synapse / Chroma": ["razer synapse", "razer chroma", "razer central", "razer\\"],
    "SteelSeries GG / Engine": ["steelseries"],
    "NZXT CAM": ["nzxt cam", "nzxt\\cam"],
    "Cooler Master MasterPlus+": ["masterplus", "cooler master", "masterctrl"],
    "Thermaltake TT RGB Plus": ["tt rgb plus", "thermaltake"],
    "Lian Li L-Connect": ["l-connect", "lian li", "lianli"],
    "HyperX NGENUITY": ["ngenuity", "hyperx"],
    "ROCCAT Swarm": ["roccat"],
    "Alienware Command Center": ["alienware command center", "awcc", "alienfx"],
    "EVGA Precision X1": ["precision x1", "evga"],
    "Kingston FURY CTRL": ["fury ctrl", "kingston fury"],
    "G.Skill Lighting Control": ["trident z lighting", "g.skill", "gskill"],
    "TeamGroup T-Force Blitz": ["t-force blitz", "teamgroup"],
    "ADATA XPG Prime": ["xpg prime", "xpg rgb"],
    "Patriot Viper RGB": ["viper rgb", "patriot"],
    "Crucial M.O.D.": ["ballistix m.o.d", "crucial m.o.d"],
    "Deepcool": ["deepcool"],
    "Phanteks": ["phanteks"],
    "SignalRGB": ["signalrgb", "whirlwindfx", "vortxengine"],
    "OpenRGB (separat installiert)": ["openrgb"],
}

# Nie anfassen (eigene RGB-Engine, Windows selbst)
_IGNORE = ["\\windows\\system32\\", "\\windows\\syswow64\\", "_mei", "cs2localclaude"]


def _powershell(script: str, timeout: int = 45) -> str:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                            capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
    return result.stdout.decode("utf-8", errors="replace")


def match(*texts) -> str | None:
    blob = " ".join((t or "").lower().replace("/", "\\") for t in texts)
    if any(skip in blob for skip in _IGNORE):
        return None
    for name, words in CATALOG.items():
        if any(w in blob for w in words):
            return name
    return None


_SCAN_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$cmd = @{}; $parent = @{}
Get-CimInstance Win32_Process | ForEach-Object { $cmd[[int]$_.ProcessId] = $_.CommandLine;
                                                 $parent[[int]$_.ProcessId] = $_.ParentProcessId }
$procs = Get-Process | Where-Object { $_.Path } | ForEach-Object {
  [pscustomobject]@{ pid=$_.Id; name=$_.ProcessName; path=$_.Path; company=$_.Company; product=$_.Product;
                     cmd=$cmd[[int]$_.Id]; parent=$parent[[int]$_.Id] } }
$svcs = Get-CimInstance Win32_Service | ForEach-Object {
  [pscustomobject]@{ name=$_.Name; display=$_.DisplayName; path=$_.PathName; state=$_.State; pid=$_.ProcessId } }
$keys = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
$apps = Get-ItemProperty $keys | Where-Object { $_.DisplayName } | ForEach-Object {
  [pscustomobject]@{ name=$_.DisplayName; publisher=$_.Publisher; location=$_.InstallLocation } }
$store = Get-AppxPackage -AllUsers | ForEach-Object {
  $id = ''
  try { $m = Get-AppxPackageManifest $_; $id = $_.PackageFamilyName + '!' + $m.Package.Applications.Application[0].Id } catch {}
  [pscustomobject]@{ name=$_.Name; publisher=$_.Publisher; location=$_.InstallLocation; aumid=$id } }
@{ processes=@($procs); services=@($svcs); installed=@($apps); store=@($store) } | ConvertTo-Json -Depth 4 -Compress
"""


def scan() -> dict:
    """Ergebnis: {Anzeigename: {"installed": bool, "services": [...], "processes": [...]}}."""
    if os.name != "nt":
        return {}
    try:
        raw = _powershell(_SCAN_SCRIPT)
        data = json.loads(raw[raw.find("{"):]) if "{" in raw else {}
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Software-Prüfung nicht möglich: %s", exc)
        return {}
    found: dict = {}

    def entry(name):
        return found.setdefault(name, {"installed": False, "services": [], "processes": []})

    store_ids = []
    for app in data.get("store") or []:
        name = match(app.get("name"), app.get("publisher"), app.get("location"))
        if name:
            entry(name)["installed"] = True
            store_ids.append((str(app.get("location") or "").lower(), app.get("aumid") or ""))
    for app in data.get("installed") or []:
        name = match(app.get("name"), app.get("publisher"), app.get("location"))
        if name:
            entry(name)["installed"] = True
    service_pids = set()
    for svc in data.get("services") or []:
        name = match(svc.get("name"), svc.get("display"), svc.get("path"))
        if not name:
            continue
        entry(name)["installed"] = True
        if svc.get("state") == "Running":
            entry(name)["services"].append({"name": svc["name"], "display": svc.get("display") or svc["name"]})
            service_pids.add(svc.get("pid"))
    own = os.getpid()
    for proc in data.get("processes") or []:
        if proc.get("pid") in (own, *service_pids):
            continue
        name = match(proc.get("path"), proc.get("company"), proc.get("product"))
        if not name:
            continue
        path = proc["path"]
        aumid = next((a for loc, a in store_ids if loc and a and path.lower().startswith(loc)), "")
        entry(name)["installed"] = True
        helper = proc.get("parent") in service_pids or "crashpad" in (proc.get("name") or "").lower() \
            or "updat" in (proc.get("name") or "").lower()
        entry(name)["processes"].append({"pid": proc["pid"], "name": proc.get("name"), "path": path,
                                         "cmd": proc.get("cmd") or f'"{path}"', "aumid": aumid, "helper": helper})
    log.info("Software-Prüfung: %s", {k: ("läuft" if v["services"] or v["processes"] else "installiert")
                                      for k, v in found.items()})
    return found


def running(found: dict) -> dict:
    return {k: v for k, v in found.items() if v["services"] or v["processes"]}


def pause(found: dict) -> list:
    """Stoppt Dienste und beendet Programme der laufenden Software. Gibt zurück, was sich nicht stoppen liess."""
    failed = []
    restart = {"services": [], "processes": []}
    for vendor, items in running(found).items():
        for svc in items["services"]:
            out = _powershell(f"try {{ Stop-Service -Name '{svc['name']}' -Force -ErrorAction Stop; 'ok' }} "
                              f"catch {{ $_.Exception.Message }}")
            if out.strip().endswith("ok"):
                restart["services"].append(svc["name"])
            else:
                failed.append(f"{svc['display']}: {out.strip()[:80]}")
        seen = set()
        for proc in items["processes"]:
            result = subprocess.run(["taskkill", "/F", "/PID", str(proc["pid"])], capture_output=True,
                                    timeout=15, creationflags=_NO_WINDOW)
            if result.returncode in (0, 128):
                key = proc.get("aumid") or proc["cmd"]
                if proc.get("helper"):  # Hilfsprozess: startet sein Dienst/Programm selbst wieder
                    continue
                if key not in seen:
                    restart["processes"].append({"cmd": proc["cmd"], "path": proc["path"], "vendor": vendor,
                                                 "aumid": proc.get("aumid", "")})
                    seen.add(key)
            else:
                failed.append(proc["name"])
    _save_pending(restart)
    log.info("Pausiert: %d Dienste, %d Programme, Fehler: %s", len(restart["services"]),
             len(restart["processes"]), failed)
    return failed


def _save_pending(restart: dict) -> None:
    old = load_pending()
    known = {p.get("aumid") or p["cmd"] for p in old["processes"]}
    merged = {"services": list(dict.fromkeys(old["services"] + restart["services"])),
              "processes": old["processes"] + [p for p in restart["processes"]
                                               if (p.get("aumid") or p["cmd"]) not in known]}
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


def has_pending() -> bool:
    pending = load_pending()
    return bool(pending["services"] or pending["processes"])


def resume() -> list:
    """Startet alles wieder, was das Tool pausiert hat. Gibt Fehler zurück."""
    pending = load_pending()
    errors = []
    for name in pending["services"]:
        out = _powershell(f"try {{ Start-Service -Name '{name}' -ErrorAction Stop; 'ok' }} catch {{ $_.Exception.Message }}")
        if not out.strip().endswith("ok"):
            errors.append(f"Dienst {name}: {out.strip()[:80]}")
    if pending["services"]:
        time.sleep(3.0)  # Dienste starten ihre Programme oft selbst
    running_now = {(p or "").lower() for p in _running_paths()}
    started_apps = set()
    for proc in pending["processes"]:
        if proc["path"].lower() in running_now:
            continue
        try:
            if proc.get("aumid"):  # Microsoft-Store-App: über ihre App-ID starten
                if proc["aumid"] in started_apps:
                    continue
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{proc['aumid']}"], creationflags=_DETACHED)
                started_apps.add(proc["aumid"])
            else:
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
        raw = _powershell("Get-Process | Where-Object { $_.Path } | ForEach-Object { $_.Path }")
        return [line.strip() for line in raw.splitlines() if line.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []
