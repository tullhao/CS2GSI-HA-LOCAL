"""CS2 auf dem PC finden und die Game-State-Integration-Datei schreiben."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

CS2_APPID = "730"
GSI_FILENAME = "gamestate_integration_cs2localclaude.cfg"

GSI_TEMPLATE = """"CS2 Local Claude"
{{
    "uri"       "http://127.0.0.1:{port}"
    "timeout"   "1.1"
    "buffer"    "0.0"
    "throttle"  "0.05"
    "heartbeat" "10.0"
    "auth"
    {{
        "token" "{token}"
    }}
    "data"
    {{
        "provider"           "1"
        "map"                "1"
        "round"              "1"
        "player_id"          "1"
        "player_state"       "1"
        "player_weapons"     "1"
        "player_match_stats" "1"
        "bomb"               "1"
    }}
}}
"""


def _registry_steam_paths() -> list[Path]:
    paths: list[Path] = []
    if os.name != "nt":
        return paths
    import winreg  # nur unter Windows vorhanden

    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, sub, name in keys:
        try:
            with winreg.OpenKey(hive, sub) as key:
                value, _ = winreg.QueryValueEx(key, name)
                paths.append(Path(value))
        except OSError:
            pass
    return paths


def steam_paths() -> list[Path]:
    candidates = _registry_steam_paths() + [
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
    ]
    seen, out = set(), []
    for p in candidates:
        key = str(p).lower().replace("/", "\\")
        if key not in seen and p.is_dir():
            seen.add(key)
            out.append(p)
    return out


def parse_library_folders(text: str) -> list[Path]:
    """Liest die Bibliotheksordner aus steamapps/libraryfolders.vdf."""
    return [Path(m.replace("\\\\", "\\")) for m in re.findall(r'"path"\s+"([^"]+)"', text)]


def library_folders(steam: Path) -> list[Path]:
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    try:
        return parse_library_folders(vdf.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return []


def is_cs2_dir(path: Path) -> bool:
    return (path / "game" / "csgo").is_dir()


def normalize_cs2_dir(path: Path) -> Path | None:
    """Akzeptiert auch Unterordner (z. B. game/csgo/cfg) und geht hoch bis zum CS2-Hauptordner."""
    path = Path(path)
    for candidate in [path, *path.parents]:
        if is_cs2_dir(candidate):
            return candidate
    return None


def find_cs2() -> Path | None:
    for steam in steam_paths():
        for lib in [steam, *library_folders(steam)]:
            installdir = "Counter-Strike Global Offensive"
            manifest = lib / "steamapps" / f"appmanifest_{CS2_APPID}.acf"
            if manifest.exists():
                try:
                    match = re.search(r'"installdir"\s+"([^"]+)"',
                                      manifest.read_text(encoding="utf-8", errors="ignore"))
                    if match:
                        installdir = match.group(1)
                except OSError:
                    pass
            candidate = lib / "steamapps" / "common" / installdir
            if is_cs2_dir(candidate):
                log.info("CS2 gefunden: %s", candidate)
                return candidate
    log.info("CS2 nicht automatisch gefunden")
    return None


def cfg_dir(cs2: Path) -> Path:
    return cs2 / "game" / "csgo" / "cfg"


def gsi_file(cs2: Path) -> Path:
    return cfg_dir(cs2) / GSI_FILENAME


def other_gsi_files(cs2: Path) -> list[str]:
    """Andere GSI-Dateien (z. B. Home Assistant oder die alte local_pc-Bridge). CS2 bedient alle parallel."""
    try:
        return sorted(p.name for p in cfg_dir(cs2).glob("gamestate_integration_*.cfg") if p.name != GSI_FILENAME)
    except OSError:
        return []


def write_gsi_config(cs2: Path, port: int, token: str) -> tuple[Path, bool]:
    """Schreibt die Config. Gibt (Pfad, geändert) zurück. 'geändert' heisst: CS2 muss neu gestartet werden, falls es läuft."""
    target = gsi_file(cs2)
    content = GSI_TEMPLATE.format(port=port, token=token)
    try:
        old = target.read_text(encoding="utf-8")
    except OSError:
        old = None
    if old == content:
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    log.info("GSI-Config geschrieben: %s", target)
    return target, True
