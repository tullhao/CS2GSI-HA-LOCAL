"""Übersetzt die rohen GSI-Daten von CS2 in aktive Licht-Zustände und kurze Ereignisse."""
from __future__ import annotations

import threading
import time


def _num(value, default=0):
    try:
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def _active_weapon(player: dict) -> dict | None:
    for weapon in (player.get("weapons") or {}).values():
        if isinstance(weapon, dict) and weapon.get("state") in ("active", "reloading"):
            return weapon
    return None


class StateDetector:
    TIMEOUT = 35.0  # Sekunden ohne Daten -> CS2 gilt als nicht verbunden

    def __init__(self, get_options):
        self._get_options = get_options
        self._lock = threading.Lock()
        self._states: dict[str, float] = {}   # Zustand -> seit wann aktiv
        self._alpha: dict[str, float] = {}    # Zustand -> Stärke 0..1
        self._events: dict[str, float] = {}   # Ereignis -> Startzeit
        self._prev: dict = {}
        self._prev_own = False
        self._my_team: str | None = None
        self.last_update = 0.0
        self.info: dict = {}

    @property
    def team(self) -> str | None:
        return self._my_team

    # ---------------------------------------------------------------- Eingang
    def update(self, data: dict, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        opts = self._get_options()
        with self._lock:
            self._update(data, now, opts)
            self.last_update = now

    def _fire(self, sid: str, now: float) -> None:
        self._events[sid] = now

    def _update(self, data: dict, now: float, opts: dict) -> None:
        provider = data.get("provider") or {}
        player = data.get("player") or {}
        mp = data.get("map") or {}
        rnd = data.get("round") or {}
        ps = player.get("state") or {}

        own_id = provider.get("steamid")
        is_own = bool(own_id) and player.get("steamid") == own_id
        if is_own and player.get("team") in ("CT", "T"):
            self._my_team = player["team"]
        team = self._my_team

        prev_rnd = self._prev.get("round") or {}
        prev_ps = (self._prev.get("player") or {}).get("state") or {}

        active: dict[str, float] = {}
        in_game = bool(mp) and player.get("activity") != "menu"
        health = int(_num(ps.get("health"))) if is_own and "health" in ps else None
        bomb = rnd.get("bomb")

        if not in_game:
            active["idle"] = 1.0
        else:
            if team == "CT":
                active["team_ct"] = 1.0
            elif team == "T":
                active["team_t"] = 1.0
            else:
                active["idle"] = 1.0

            if mp.get("phase") == "warmup":
                active["warmup"] = 1.0
            elif rnd.get("phase") == "freezetime":
                active["freezetime"] = 1.0

            if player and (not is_own or health == 0):
                active["dead"] = 1.0

            if is_own and health:
                crit = int(opts.get("critical_health_threshold", 15))
                low = int(opts.get("low_health_threshold", 30))
                if health <= crit:
                    active["critical_health"] = 1.0
                elif health <= low:
                    active["low_health"] = 1.0
                flashed = _num(ps.get("flashed"))
                if flashed > 0:
                    active["flashed"] = min(1.0, flashed / 255.0)
                burning = _num(ps.get("burning"))
                if burning > 0:
                    active["burning"] = max(0.4, min(1.0, burning / 255.0))
                smoked = _num(ps.get("smoked"))
                if smoked > 0:
                    active["smoked"] = max(0.3, min(1.0, smoked / 255.0))
                weapon = _active_weapon(player)
                if weapon:
                    if weapon.get("state") == "reloading":
                        active["reloading"] = 1.0
                    else:
                        clip, clip_max = weapon.get("ammo_clip"), weapon.get("ammo_clip_max")
                        pct = float(opts.get("low_ammo_percent", 25))
                        if clip is not None and clip_max and clip_max > 1 and clip * 100 <= clip_max * pct:
                            active["low_ammo"] = 1.0

            if bomb == "planted":
                active["bomb_planted"] = 1.0
                c4 = ps.get("health_c4_preview") if is_own else None
                if c4 is not None and health and _num(c4, 1) <= 0:
                    active["bomb_lethal"] = 1.0
            elif bomb == "exploded":
                active["bomb_exploded"] = 1.0  # bleibt bis zur nächsten Runde (wie im alten Bridge)

            # Ereignisse: Übergänge im Vergleich zum letzten Paket
            if self._prev:
                if bomb == "defused" and prev_rnd.get("bomb") != "defused":
                    self._fire("bomb_defused", now)
                if rnd.get("phase") == "over" and prev_rnd.get("phase") != "over":
                    win = rnd.get("win_team")
                    if win and team:
                        self._fire("round_won" if win == team else "round_lost", now)
                if is_own and self._prev_own:
                    if _num(ps.get("round_killhs")) > _num(prev_ps.get("round_killhs")):
                        self._fire("headshot", now)
                    elif _num(ps.get("round_kills")) > _num(prev_ps.get("round_kills")):
                        self._fire("kill", now)
                    prev_health = _num(prev_ps.get("health"), None)
                    if (health and prev_health is not None and health < prev_health
                            and "flashed" not in active and "burning" not in active and bomb != "planted"):
                        self._fire("damage", now)

        self._states = {sid: self._states.get(sid, now) for sid in active}
        self._alpha = active
        self._prev = data
        self._prev_own = is_own
        self.info = {
            "map": mp.get("name"),
            "map_phase": mp.get("phase"),
            "round_phase": rnd.get("phase"),
            "bomb": bomb,
            "team": team,
            "own": is_own,
            "activity": player.get("activity"),
            "health": health,
            "armor": ps.get("armor") if is_own else None,
            "c4_preview": ps.get("health_c4_preview") if is_own else None,
        }

    # ---------------------------------------------------------------- Ausgang
    def connected(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.last_update > 0 and now - self.last_update < self.TIMEOUT

    def snapshot(self, now: float, states_cfg: dict) -> dict[str, tuple[float, float]]:
        """Aktive Ebenen: Zustand -> (Alter in s, Stärke 0..1)."""
        with self._lock:
            if not self.connected(now):
                return {"idle": (now, 1.0)}
            out = {sid: (now - start, self._alpha.get(sid, 1.0)) for sid, start in self._states.items()}
            for sid, start in list(self._events.items()):
                duration = float(states_cfg.get(sid, {}).get("duration") or 1.0)
                age = now - start
                if age > duration:
                    del self._events[sid]
                else:
                    out[sid] = (age, 1.0)
            return out

    def active_names(self, now: float, states_cfg: dict) -> list[str]:
        snap = self.snapshot(now, states_cfg)
        ids = sorted(snap, key=lambda s: -states_cfg.get(s, {}).get("priority", 0))
        return [states_cfg[s]["name"] for s in ids if s in states_cfg and states_cfg[s].get("enabled")]
