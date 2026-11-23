"""Pfade, Standardwerte und das Speichern/Laden der Einstellungen (portabel, neben der EXE)."""
from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path

APP_NAME = "CS2 Local Claude"
VERSION = "2.0.0"

log = logging.getLogger(__name__)


def app_dir() -> Path:
    """Ordner, in dem die EXE liegt (dort landen settings.json und das Log)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_dir() -> Path:
    """Ordner mit den eingebauten Bausteinen (in der EXE: entpackter Temp-Ordner)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else app_dir() / "bundle"


SETTINGS_FILE = app_dir() / "cs2local_settings.json"
LOG_FILE = app_dir() / "cs2local.log"
OPENRGB_DIR = resource_dir() / "openrgb"
OPENRGB_DEV_DIR = resource_dir() / "openrgb_dev"  # neueste Entwicklungsversion für sehr neue Hardware
PAWNIO_SETUP = resource_dir() / "pawnio" / "PawnIO_setup.exe"

EFFECTS = {
    "solid": "Fest",
    "blink": "Blinken",
    "pulse": "Pulsieren",
    "flicker": "Flackern",
    "chase": "Lauflicht",
    "spin": "Drehen (je Lüfter)",
    "fade": "Ausblenden",
    "flash": "Blitz (halten, dann ausblenden)",
}

# Standardwerte orientieren sich am bisherigen local_pc-Bridge (CT blau, T grün, Teamfarbe gedimmt im Spiel).
# id, Name, Art, Farbe, Teamfarbe?, Effekt, Tempo (Hz), Dauer (s), Helligkeit (%), Priorität, Beschreibung
_DEFAULT_STATES = [
    ("idle", "Menü / Leerlauf", "state", (40, 40, 70), False, "pulse", 0.2, 0, 100, 0,
     "CS2 ist nicht im Spiel (Hauptmenü oder nicht gestartet)."),
    ("team_ct", "Team CT", "state", (0, 0, 255), False, "solid", 1.0, 0, 35, 10,
     "Grundfarbe als Counter-Terrorist. Diese Farbe ist auch die „Teamfarbe“ für andere Situationen."),
    ("team_t", "Team T", "state", (0, 255, 0), False, "solid", 1.0, 0, 35, 10,
     "Grundfarbe als Terrorist. Diese Farbe ist auch die „Teamfarbe“ für andere Situationen."),
    ("warmup", "Aufwärmphase", "state", (120, 120, 255), True, "pulse", 0.4, 0, 60, 15, "Warmup vor dem Match."),
    ("freezetime", "Kaufphase", "state", (255, 255, 255), True, "solid", 1.0, 0, 100, 20,
     "Freezetime zu Rundenbeginn: volle Teamfarbe."),
    ("smoked", "In der Smoke", "state", (24, 24, 24), True, "solid", 1.0, 0, 12, 25, "Du stehst in einer Smoke."),
    ("dead", "Tot / Zuschauer", "state", (30, 0, 0), False, "solid", 1.0, 0, 100, 30, "Du bist tot und schaust zu."),
    ("low_ammo", "Munition knapp", "state", (255, 120, 0), False, "blink", 2.0, 0, 100, 32,
     "Magazin der aktiven Waffe fast leer (Schwelle unter Optionen)."),
    ("reloading", "Nachladen", "state", (0, 220, 255), False, "chase", 1.5, 0, 100, 34, "Während du nachlädst."),
    ("low_health", "Wenig Leben", "state", (255, 255, 255), True, "pulse", 0.37, 0, 35, 40,
     "Leben unter der Schwelle „Wenig Leben“: Teamfarbe pulsiert."),
    ("critical_health", "Kritisches Leben", "state", (255, 0, 0), False, "pulse", 0.37, 0, 100, 42,
     "Leben unter der Schwelle „Kritisch“: rot pulsierend."),
    ("damage", "Treffer kassiert", "event", (255, 255, 255), True, "solid", 1.0, 0.5, 100, 45,
     "Kurz volle Teamfarbe, wenn du Schaden nimmst."),
    ("bomb_planted", "Bombe gelegt", "state", (255, 0, 0), False, "blink", 1.0, 0, 100, 50,
     "Blinkt immer schneller, je näher die Explosion kommt."),
    ("bomb_lethal", "Bombe wäre tödlich", "state", (170, 0, 255), False, "pulse", 3.0, 0, 100, 55,
     "Neu in CS2 (health_c4_preview): Die Explosion würde dich an deiner Position töten."),
    ("burning", "Brennend", "state", (255, 80, 0), False, "flicker", 5.0, 0, 100, 60, "Du stehst im Feuer (Molotov)."),
    ("kill", "Kill", "event", (0, 255, 60), False, "fade", 1.0, 0.6, 100, 70, "Kurzer Effekt bei einem Kill."),
    ("headshot", "Headshot", "event", (255, 0, 200), False, "fade", 1.0, 0.8, 100, 72,
     "Kurzer Effekt bei einem Headshot-Kill."),
    ("round_lost", "Runde verloren", "event", (60, 0, 0), False, "solid", 1.0, 4.0, 100, 74,
     "Dein Team hat die Runde verloren."),
    ("round_won", "Runde gewonnen", "event", (255, 255, 255), True, "solid", 1.0, 4.0, 100, 75,
     "Dein Team hat die Runde gewonnen: volle Teamfarbe."),
    ("bomb_defused", "Bombe entschärft", "event", (0, 0, 255), False, "blink", 1.67, 3.0, 100, 80,
     "Die Bombe wurde entschärft: blau blinkend."),
    ("bomb_exploded", "Bombe explodiert", "state", (255, 0, 0), False, "solid", 1.0, 0, 100, 80,
     "Die Bombe ist explodiert: rot bis zur nächsten Runde."),
    ("flashed", "Geblendet (Flash)", "event", (255, 255, 255), False, "flash", 1.0, 2.5, 100, 100,
     "Bei jeder Flashbang: kurz voll weiss, dann langsam ausblenden (wie im alten Bridge)."),
    # --- weitere Spielzustände aus der Game State Integration
    ("bomb_critical", "Bombe kritisch", "state", (255, 0, 0), False, "blink", 6.0, 0, 100, 54,
     "Die letzten 10 Sekunden vor der Explosion: schnelles Stroboskop."),
    ("carrying_bomb", "Du trägst die Bombe", "state", (255, 140, 0), False, "pulse", 0.5, 0, 40, 21,
     "Die C4 ist in deinem Inventar."),
    ("knife_out", "Messer in der Hand", "state", (220, 220, 220), True, "solid", 1.0, 0, 60, 11,
     "Dein Messer ist gezogen (z. B. beim Laufen)."),
    ("grenade_out", "Granate in der Hand", "state", (120, 255, 120), False, "pulse", 1.2, 0, 60, 13,
     "Du hältst eine Granate."),
    ("no_armor", "Keine Rüstung", "state", (255, 200, 0), False, "pulse", 0.6, 0, 40, 24,
     "Du lebst, hast aber keine Kevlar-Weste."),
    ("halftime", "Halbzeit", "state", (90, 90, 255), False, "pulse", 0.3, 0, 70, 18, "Seitenwechsel zur Halbzeit."),
    ("matchpoint", "Matchpoint", "state", (255, 255, 255), True, "pulse", 1.0, 0, 70, 14,
     "Ein Team braucht nur noch eine Runde zum Sieg."),
    ("death", "Gestorben", "event", (255, 0, 0), False, "fade", 1.0, 1.5, 100, 85, "Kurzer roter Blitz, wenn du stirbst."),
    ("assist", "Assist", "event", (0, 180, 255), False, "fade", 1.0, 0.5, 100, 69, "Du hast bei einem Kill geholfen."),
    ("triple_kill", "Triple Kill", "event", (255, 215, 0), False, "blink", 4.0, 1.5, 100, 76, "3 Kills in einer Runde."),
    ("quad_kill", "Quad Kill", "event", (255, 120, 0), False, "blink", 5.0, 2.0, 100, 77, "4 Kills in einer Runde."),
    ("ace", "Ace", "event", (255, 0, 255), False, "chase", 2.0, 3.0, 100, 78, "5 Kills in einer Runde – das ganze Team."),
    ("mvp", "MVP", "event", (255, 215, 0), False, "pulse", 1.5, 4.0, 100, 79, "Du bist MVP der Runde."),
    ("match_won", "Match gewonnen", "event", (255, 255, 255), True, "blink", 2.0, 8.0, 100, 90,
     "Spielende: dein Team hat gewonnen."),
    ("match_lost", "Match verloren", "event", (60, 0, 0), False, "fade", 1.0, 8.0, 100, 90,
     "Spielende: dein Team hat verloren."),
]

DEFAULT_DISABLED = {"knife_out", "grenade_out", "no_armor"}  # eher Geschmackssache, standardmässig aus

STATE_ORDER = [s[0] for s in _DEFAULT_STATES]

# Kategorien der Effekt-Seite: (Titel, Erklärung, Zustände, Einstellungen der Kategorie)
CATEGORIES = [
    ("Grundfarben", "Die Farbe im Normalfall: im Menü, als CT oder T und zum Rundenstart.",
     ["team_ct", "team_t", "freezetime", "warmup", "idle"], []),
    ("Gesundheit", "Wie es dir geht: wenig Leben, Treffer, Rüstung und Tod.",
     ["low_health", "critical_health", "damage", "death", "dead", "no_armor"],
     [("low_health_threshold", "Wenig Leben ab", " HP", 2, 99), ("critical_health_threshold", "Kritisch ab", " HP", 1, 98)]),
    ("Kampf", "Was im Gefecht passiert: Flash, Kills, Multikills, Feuer und Smoke.",
     ["flashed", "kill", "headshot", "assist", "triple_kill", "quad_kill", "ace", "burning", "smoked"], []),
    ("Bombe", "Alles rund um die C4: tragen, gelegt, kritisch, tödlich, entschärft oder explodiert.",
     ["carrying_bomb", "bomb_planted", "bomb_critical", "bomb_lethal", "bomb_defused", "bomb_exploded"], []),
    ("Waffe", "Deine aktive Waffe: Nachladen, knappe Munition, Messer und Granaten.",
     ["reloading", "low_ammo", "knife_out", "grenade_out"], [("low_ammo_percent", "Munition knapp ab", " % im Magazin", 5, 90)]),
    ("Runde", "Rundenende, MVP und das Match: Halbzeit, Matchpoint, Sieg oder Niederlage.",
     ["round_won", "round_lost", "mvp", "halftime", "matchpoint", "match_won", "match_lost"], []),
]
STATE_KEYS = ("enabled", "color", "team_color", "effect", "speed", "duration", "intensity", "priority")

# Was an einem ARGB-Anschluss hängen kann: Name, LEDs pro Stück, Art (fan = Lüfter-Ringe, strip = Streifen)
HARDWARE_PRESETS = [
    ("Corsair LL120 / LL140", 16, "fan"),
    ("Corsair QL120 / QL140", 34, "fan"),
    ("Corsair SP120 / SP140 RGB Elite", 8, "fan"),
    ("Corsair AF120 / AF140 RGB Elite", 8, "fan"),
    ("Corsair ML120 / ML140 RGB", 4, "fan"),
    ("Corsair HD120 RGB", 12, "fan"),
    ("Corsair LED-Streifen (RGB Strip)", 10, "strip"),
    ("ARGB-Lüfter allgemein", 12, "fan"),
    ("ARGB-Streifen allgemein", 30, "strip"),
    ("Eigene Angabe", 10, "fan"),
]

DEFAULT_OPTIONS = {
    "brightness": 100,
    "fps": 20,
    "low_health_threshold": 30,
    "critical_health_threshold": 15,
    "low_ammo_percent": 25,
    "gsi_port": 3002,
    "openrgb_port": 6742,
}


def default_states() -> dict:
    out = {}
    for sid, name, kind, color, team, effect, speed, duration, intensity, prio, desc in _DEFAULT_STATES:
        out[sid] = {
            "name": name, "kind": kind, "enabled": sid not in DEFAULT_DISABLED, "color": list(color), "team_color": team,
            "effect": effect, "speed": speed, "duration": duration, "intensity": intensity,
            "priority": prio, "desc": desc,
        }
    return out


def default_settings() -> dict:
    return {
        "version": 3,
        "cs2_path": None,
        "gsi_token": None,
        "pawnio_declined": False,
        "devices": [],
        "zone_sizes": {},
        "zone_layout": {},
        "fans_off": {},
        "device_methods": {},
        "engine": "stable",
        "device_check_done": False,
        "states": default_states(),
        "options": dict(DEFAULT_OPTIONS),
    }


def load_settings() -> dict | None:
    """Lädt die letzte Sitzung. None, wenn es keine (gültige) gibt."""
    if not SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Einstellungen nicht lesbar: %s", exc)
        return None
    merged = default_settings()
    merged["cs2_path"] = data.get("cs2_path")
    merged["gsi_token"] = data.get("gsi_token")
    merged["pawnio_declined"] = bool(data.get("pawnio_declined", False))
    merged["devices"] = [str(k) for k in data.get("devices", [])]
    merged["zone_sizes"] = {str(k): int(v) for k, v in data.get("zone_sizes", {}).items()}
    merged["zone_layout"] = {str(k): dict(v) for k, v in data.get("zone_layout", {}).items() if isinstance(v, dict)}
    merged["device_methods"] = {str(k): str(v) for k, v in data.get("device_methods", {}).items()
                                if v in ("direct", "static")}
    merged["engine"] = "dev" if data.get("engine") == "dev" else "stable"
    merged["device_check_done"] = bool(data.get("device_check_done", False))
    merged["fans_off"] = {str(k): [int(i) for i in v] for k, v in data.get("fans_off", {}).items()}
    for key, value in data.get("options", {}).items():
        if key in DEFAULT_OPTIONS:
            merged["options"][key] = value
    if int(data.get("version", 2)) < 3:  # Flash ist jetzt ein Blitz-Ereignis statt Dauerzustand
        data.get("states", {}).pop("flashed", None)
    for sid, st in data.get("states", {}).items():
        if sid in merged["states"]:
            for key in STATE_KEYS:
                if key in st:
                    merged["states"][sid][key] = st[key]
    return merged


def save_settings(settings: dict) -> None:
    try:
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
    except OSError as exc:
        log.error("Einstellungen konnten nicht gespeichert werden: %s", exc)


def copy_settings(settings: dict) -> dict:
    return copy.deepcopy(settings)
