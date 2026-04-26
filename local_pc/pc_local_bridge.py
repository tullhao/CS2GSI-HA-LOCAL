import json
import threading
import time
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, request
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

CONFIG_PATH = Path(__file__).with_name("config.json")
app = Flask(__name__)

state_lock = threading.Lock()
latest_state: dict[str, Any] = {}
bomb_planted_monotonic: float | None = None
last_applied_key = ""
client_lock = threading.Lock()

rgb_client = None
rgb_devices = []

last_health_value: int | None = None
damage_until = 0.0
last_flashed_value: float | None = None
flash_effect_until = 0.0
flash_started_at = 0.0


def load_config() -> dict[str, Any]:
    defaults = {
        "bind_host": "127.0.0.1",
        "bind_port": 3002,
        "ha_forward_url": "http://192.168.178.111:3001/",
        "openrgb_host": "127.0.0.1",
        "openrgb_port": 6742,
        "openrgb_device_name_contains": [],
        "client_name": "CS2 Local RGB Bridge",
        "enable_forward_to_ha": True,
        "log_payloads": False,
        "flash_white_hold_seconds": 0.68,
        "flash_fade_seconds": 1.85,
    }
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        defaults.update(user)
    return defaults


CONFIG = load_config()


def deep_get(data: dict, *keys, default=None):
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def infer_time_left(now: float, planted_mono: float | None) -> float:
    if planted_mono is None:
        return 40.0
    elapsed = max(0.0, now - planted_mono)
    return max(0.0, 40.0 - elapsed)


def get_bomb_time_left(data: dict[str, Any], now: float) -> float:
    countdown = deep_get(data, "bomb", "countdown", default=None)
    try:
        if countdown not in (None, ""):
            return max(0.0, float(countdown))
    except Exception:
        pass
    return infer_time_left(now, bomb_planted_monotonic)


def calc_visual_period_seconds(time_left: float) -> float:
    if time_left <= 0:
        return 0.15
    return max(0.15, 0.1 + 0.9 * (time_left / 40.0))


def connect_openrgb():
    global rgb_client, rgb_devices
    rgb_client = OpenRGBClient(
        CONFIG["openrgb_host"],
        int(CONFIG["openrgb_port"]),
        CONFIG["client_name"],
    )

    wanted = [x.lower() for x in CONFIG.get("openrgb_device_name_contains", [])]
    devices = []
    for dev in rgb_client.devices:
        name = getattr(dev, "name", "")
        if not wanted or any(w in name.lower() for w in wanted):
            devices.append(dev)

    rgb_devices = devices
    print("Connected to OpenRGB devices:", [d.name for d in rgb_devices], flush=True)
    if not rgb_devices:
        raise RuntimeError("No matching OpenRGB devices found. Check config.json device name filter.")


def ensure_direct_or_static(dev):
    mode_names = [getattr(m, "name", "").lower() for m in getattr(dev, "modes", [])]
    for preferred in ("direct", "static"):
        if preferred in mode_names:
            try:
                dev.set_mode(preferred)
                time.sleep(0.05)
                return
            except Exception:
                pass


def set_devices_color(r: int, g: int, b: int):
    global last_applied_key
    key = f"on:{r},{g},{b}"
    if key == last_applied_key:
        return
    with client_lock:
        for dev in rgb_devices:
            try:
                ensure_direct_or_static(dev)
                dev.set_color(RGBColor(r, g, b))
                time.sleep(0.02)
            except Exception as e:
                print(f"OpenRGB set_color failed on {getattr(dev, 'name', '?')}: {e}", flush=True)
    last_applied_key = key


def turn_devices_off():
    global last_applied_key
    if last_applied_key == "off":
        return
    with client_lock:
        for dev in rgb_devices:
            try:
                ensure_direct_or_static(dev)
                dev.set_color(RGBColor(0, 0, 0))
                time.sleep(0.02)
            except Exception as e:
                print(f"OpenRGB off failed on {getattr(dev, 'name', '?')}: {e}", flush=True)
    last_applied_key = "off"


def forward_to_ha(data: dict[str, Any]):
    if not CONFIG.get("enable_forward_to_ha", True):
        return
    url = str(CONFIG.get("ha_forward_url", "")).strip()
    if not url:
        return
    try:
        requests.post(url, json=data, timeout=0.35)
    except Exception:
        pass


def team_rgb(team: str, dim: bool = False):
    if team == "CT":
        return (0, 0, 89) if dim else (0, 0, 255)
    if team == "T":
        return (0, 89, 0) if dim else (0, 255, 0)
    return (255, 255, 255) if not dim else (24, 24, 24)


def get_round_win_team(data: dict[str, Any]) -> str:
    a = str(deep_get(data, "round", "win_team", default="") or "").upper()
    if a in ("CT", "T"):
        return a

    b = str(deep_get(data, "round", "winner", default="") or "").upper()
    if b in ("CT", "T"):
        return b

    return ""


def effect_to_rgb(effect: str, team: str, data: dict[str, Any], now: float) -> tuple[int, int, int]:
    if effect == "bomb_blink":
        return (255, 0, 0)

    if effect == "exploded":
        return (255, 0, 0)

    if effect == "defused":
        return (0, 0, 255)

    if effect == "round_win":
        return team_rgb(team, dim=False)

    if effect == "damage":
        health = int(to_float(deep_get(data, "player", "state", "health", default=0)))
        if 0 < health < 16:
            return (255, 0, 0)
        if team == "CT":
            return (0, 0, 255)
        if team == "T":
            return (0, 255, 0)
        return (255, 255, 255)

    if effect == "burning":
        return (255, 80, 0)

    if effect == "smoke":
        if team == "CT":
            return (0, 0, 31)
        if team == "T":
            return (0, 31, 0)
        return (24, 24, 24)

    if effect == "low_hp_team":
        cycle = 2.7
        phase = (now % cycle) / cycle
        level = 1.0 - abs(2 * phase - 1)
        pct = 0.05 + (0.35 - 0.05) * level
        if team == "CT":
            return (0, 0, int(255 * pct))
        return (0, int(255 * pct), 0)

    if effect == "critical_hp":
        cycle = 2.7
        phase = (now % cycle) / cycle
        level = 1.0 - abs(2 * phase - 1)
        pct = 0.05 + (1.0 - 0.05) * level
        return (int(255 * pct), 0, 0)

    if effect == "freeze":
        return team_rgb(team, dim=False)

    if effect in ("live", "fallback"):
        return team_rgb(team, dim=True)

    return (0, 0, 0)


def derive_context(data: dict[str, Any], now: float, ignore_flash: bool = False):
    global bomb_planted_monotonic, damage_until, flash_effect_until

    round_phase = str(deep_get(data, "round", "phase", default="") or "").lower()
    round_bomb = str(deep_get(data, "round", "bomb", default="") or "").lower()
    bomb_state = str(deep_get(data, "bomb", "state", default=round_bomb) or "").lower()

    burning = to_float(deep_get(data, "player", "state", "burning", default=0))
    smoked = to_float(deep_get(data, "player", "state", "smoked", default=0))
    health = int(to_float(deep_get(data, "player", "state", "health", default=0)))
    team = str(deep_get(data, "player", "team", default="") or "").upper()
    win_team = get_round_win_team(data)

    planted = bomb_state == "planted" or round_bomb == "planted"
    defused = bomb_state == "defused" or round_bomb == "defused"
    exploded = bomb_state == "exploded" or round_bomb == "exploded"

    if planted and bomb_planted_monotonic is None:
        bomb_planted_monotonic = now
    if not planted:
        bomb_planted_monotonic = None

    if not ignore_flash and now < flash_effect_until:
        return ("flash", team)

    if planted:
        return ("bomb_blink", team)

    if defused:
        return ("defused", team)

    if exploded:
        return ("exploded", team)

    if round_phase in ("over", "gameover") and win_team in ("CT", "T") and not exploded and not defused:
        return ("round_win", win_team)

    if now < damage_until:
        return ("damage", team)

    if burning > 0:
        return ("burning", team)

    if smoked > 0:
        return ("smoke", team)

    if 0 < health < 16:
        return ("critical_hp", team)

    if 15 < health < 30:
        return ("low_hp_team", team)

    if round_phase == "freezetime":
        return ("freeze", team)

    if round_phase == "live":
        return ("live", team)

    return ("fallback", team)


def blink_worker():
    global damage_until

    bomb_pulse_state = False
    next_flip = 0.0

    effect_phase = 0
    next_effect = 0.0
    defused_until = 0.0
    exploded_hold_active = False

    while True:
        time.sleep(0.02)

        with state_lock:
            data = dict(latest_state)

        now = time.monotonic()

        if not data:
            bomb_pulse_state = False
            next_flip = 0.0
            exploded_hold_active = False
            turn_devices_off()
            continue

        effect, team = derive_context(data, now)
        round_phase = str(deep_get(data, "round", "phase", default="") or "").lower()
        round_bomb = str(deep_get(data, "round", "bomb", default="") or "").lower()
        bomb_state = str(deep_get(data, "bomb", "state", default=round_bomb) or "").lower()

        if effect == "bomb_blink":
            countdown = get_bomb_time_left(data, now)
            period = calc_visual_period_seconds(countdown)
            on_time = min(0.30, max(0.14, period * 0.48))
            off_time = max(0.06, period - on_time)

            if next_flip <= 0.0:
                bomb_pulse_state = False
                next_flip = now + on_time

            while now >= next_flip:
                bomb_pulse_state = not bomb_pulse_state
                next_flip += off_time if bomb_pulse_state else on_time

            if bomb_pulse_state:
                turn_devices_off()
            else:
                set_devices_color(255, 0, 0)

            continue

        bomb_pulse_state = False
        next_flip = 0.0

        if effect == "exploded" or bomb_state == "exploded" or round_bomb == "exploded":
            exploded_hold_active = True

        if exploded_hold_active:
            if round_phase == "freezetime":
                exploded_hold_active = False
            else:
                set_devices_color(255, 0, 0)
                continue

        if effect == "defused":
            defused_until = max(defused_until, now + 3.0)
        if now < defused_until:
            if int(now / 0.3) % 2 == 0:
                set_devices_color(0, 0, 255)
            else:
                turn_devices_off()
            continue

        if effect == "round_win":
            set_devices_color(*team_rgb(team, dim=False))
            continue

        if effect == "flash":
            elapsed = max(0.0, now - flash_started_at)
            white_hold = float(CONFIG.get("flash_white_hold_seconds", 0.68))
            fade_time = float(CONFIG.get("flash_fade_seconds", 1.85))

            if elapsed <= white_hold:
                set_devices_color(255, 255, 255)
            else:
                base_effect, base_team = derive_context(data, now, ignore_flash=True)
                br, bg, bb = effect_to_rgb(base_effect, base_team, data, now)
                t = min(1.0, (elapsed - white_hold) / fade_time)

                r = int(round(255 + (br - 255) * t))
                g = int(round(255 + (bg - 255) * t))
                b = int(round(255 + (bb - 255) * t))
                set_devices_color(r, g, b)

            continue

        if effect == "damage":
            health = int(to_float(deep_get(data, "player", "state", "health", default=0)))
            if 0 < health < 16:
                set_devices_color(255, 0, 0)
            elif team == "CT":
                set_devices_color(0, 0, 255)
            elif team == "T":
                set_devices_color(0, 255, 0)
            else:
                set_devices_color(255, 255, 255)
            continue

        if effect == "burning":
            if now >= next_effect:
                effect_phase = (effect_phase + 1) % 4
                next_effect = now + [0.28, 0.22, 0.18, 0.28][effect_phase]
            burning_colors = [
                (255, 80, 0),
                (255, 20, 0),
                (255, 120, 0),
                (190, 10, 0),
            ]
            set_devices_color(*burning_colors[effect_phase])
            continue

        if effect == "smoke":
            if team == "CT":
                set_devices_color(0, 0, 31)
            elif team == "T":
                set_devices_color(0, 31, 0)
            else:
                set_devices_color(24, 24, 24)
            continue

        if effect == "low_hp_team":
            cycle = 2.7
            phase = (now % cycle) / cycle
            level = 1.0 - abs(2 * phase - 1)
            pct = 0.05 + (0.35 - 0.05) * level
            if team == "CT":
                set_devices_color(0, 0, int(255 * pct))
            else:
                set_devices_color(0, int(255 * pct), 0)
            continue

        if effect == "critical_hp":
            cycle = 2.7
            phase = (now % cycle) / cycle
            level = 1.0 - abs(2 * phase - 1)
            pct = 0.05 + (1.0 - 0.05) * level
            set_devices_color(int(255 * pct), 0, 0)
            continue

        if effect == "freeze":
            set_devices_color(*team_rgb(team, dim=False))
            continue

        if effect in ("live", "fallback"):
            set_devices_color(*team_rgb(team, dim=True))
            continue

        turn_devices_off()


def ingest_payload(data: dict[str, Any]):
    global last_health_value, damage_until
    global last_flashed_value, flash_effect_until, flash_started_at

    now = time.monotonic()

    health = int(to_float(deep_get(data, "player", "state", "health", default=0)))
    flashed = to_float(deep_get(data, "player", "state", "flashed", default=0))
    burning = to_float(deep_get(data, "player", "state", "burning", default=0))
    round_bomb = str(deep_get(data, "round", "bomb", default="") or "").lower()
    bomb_state = str(deep_get(data, "bomb", "state", default=round_bomb) or "").lower()
    planted = bomb_state == "planted" or round_bomb == "planted"
    ended = bomb_state in ("exploded", "defused") or round_bomb in ("exploded", "defused")

    white_hold = float(CONFIG.get("flash_white_hold_seconds", 0.68))
    fade_time = float(CONFIG.get("flash_fade_seconds", 1.85))

    if flashed > 0 and (last_flashed_value is None or last_flashed_value < 1):
        flash_started_at = now
        flash_effect_until = now + white_hold + fade_time

    last_flashed_value = flashed

    if last_health_value is not None:
        if (
            health > 0
            and health < last_health_value
            and flashed < 1
            and burning < 1
            and not planted
            and not ended
        ):
            damage_until = max(damage_until, now + 0.5)

    last_health_value = health

    with state_lock:
        latest_state.clear()
        latest_state.update(data)

    if CONFIG.get("log_payloads"):
        print(json.dumps(data, ensure_ascii=False)[:2000], flush=True)

    forward_to_ha(data)


@app.post("/")
def ingest_root():
    data = request.get_json(silent=True) or {}
    ingest_payload(data)
    return jsonify({"ok": True})


@app.post("/gsi")
def ingest_gsi():
    data = request.get_json(silent=True) or {}
    ingest_payload(data)
    return jsonify({"ok": True})


if __name__ == "__main__":
    connect_openrgb()
    threading.Thread(target=blink_worker, daemon=True).start()
    print(
        f"Starting CS2 local RGB bridge on http://{CONFIG['bind_host']}:{CONFIG['bind_port']} "
        f"-> OpenRGB {CONFIG['openrgb_host']}:{CONFIG['openrgb_port']}",
        flush=True,
    )
    app.run(host=CONFIG["bind_host"], port=int(CONFIG["bind_port"]))
