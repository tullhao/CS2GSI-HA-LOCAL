"""Tests der Kernlogik ohne Windows, Qt oder RGB-Geräte: python tests/test_core.py"""
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2local import config  # noqa: E402
from cs2local.cs2_setup import (  # noqa: E402
    normalize_cs2_dir, other_gsi_files, parse_library_folders, write_gsi_config,
)
from cs2local.engine import LightEngine, state_color  # noqa: E402
from cs2local.gsi_server import GSIServer  # noqa: E402
from cs2local.states import StateDetector  # noqa: E402

ME = "76561190000000001"


def payload(**kw):
    state = {"health": 100, "armor": 100, "flashed": 0, "burning": 0, "smoked": 0,
             "round_kills": 0, "round_killhs": 0}
    state.update(kw.pop("state", {}))
    return {
        "provider": {"steamid": ME},
        "map": {"name": "de_mirage", "phase": kw.pop("map_phase", "live"), "round": 3},
        "round": kw.pop("round", {"phase": "live"}),
        "player": {"steamid": kw.pop("steamid", ME), "team": kw.pop("team", "CT"), "activity": "playing",
                   "state": state,
                   "weapons": kw.pop("weapons", {"weapon_0": {"name": "weapon_ak47", "state": "active",
                                                             "ammo_clip": 30, "ammo_clip_max": 30}})},
    }


def test_states():
    s = config.default_settings()
    d = StateDetector(lambda: s["options"])
    states = s["states"]
    snap = lambda t: set(d.snapshot(t, states))  # noqa: E731

    assert snap(0) == {"idle"}
    d.update({"provider": {"steamid": ME}, "player": {"steamid": ME, "activity": "menu"}}, now=1)
    assert snap(1) == {"idle"}
    d.update(payload(round={"phase": "freezetime"}), now=2)
    assert snap(2) == {"team_ct", "freezetime"}, snap(2)
    d.update(payload(state={"health": 25, "flashed": 128}), now=3)
    assert {"low_health", "flashed"} <= snap(3) and "damage" not in snap(3), snap(3)  # Flash statt Treffer
    d.update(payload(state={"health": 25, "flashed": 1}), now=3.05)  # schwacher Flash zählt trotzdem
    assert "flashed" in snap(3.05)
    d.update(payload(state={"health": 20}), now=3.1)
    assert "damage" in snap(3.1)
    d.update(payload(state={"health": 25, "flashed": 128}), now=3.15)
    assert d.snapshot(3, states)["flashed"][1] == 1.0  # Blitz immer voll, egal wie stark geblendet
    d.update(payload(state={"health": 10}), now=3.2)
    assert "critical_health" in snap(3.2) and "low_health" not in snap(3.2)
    d.update(payload(state={"health": 10, "round_kills": 1, "round_killhs": 1}), now=4)
    assert "headshot" in snap(4) and "kill" not in snap(4)
    assert "headshot" not in snap(10)  # Ereignis abgelaufen
    d.update(payload(state={"health": 10, "round_kills": 2, "round_killhs": 1}), now=11)
    assert "kill" in snap(11)
    d.update(payload(round={"phase": "live", "bomb": "planted"}, state={"health_c4_preview": 0}), now=12)
    assert {"bomb_planted", "bomb_lethal"} <= snap(12)
    d.update(payload(round={"phase": "over", "bomb": "defused", "win_team": "CT"}), now=20)
    assert {"bomb_defused", "round_won"} <= snap(20)
    d.update(payload(round={"phase": "over", "bomb": "exploded", "win_team": "T"}), now=21)
    assert "bomb_exploded" in snap(29)  # bleibt bis zur nächsten Runde
    d.update(payload(round={"phase": "freezetime"}), now=30)
    assert "bomb_exploded" not in snap(30)
    d.update(payload(weapons={"w": {"state": "active", "ammo_clip": 5, "ammo_clip_max": 30}}), now=31)
    assert "low_ammo" in snap(31)
    d.update(payload(weapons={"w": {"state": "reloading", "ammo_clip": 5, "ammo_clip_max": 30}}), now=32)
    assert "reloading" in snap(32)
    d.update(payload(state={"smoked": 200}), now=33)
    assert "smoked" in snap(33)
    d.update(payload(steamid="other"), now=34)
    assert "dead" in snap(34)
    d.update(payload(map_phase="warmup", round={"phase": "warmup"}), now=35)
    assert "warmup" in snap(35)
    assert snap(100) == {"idle"}  # keine Daten mehr
    print("states ok")


def test_new_states():
    s = config.default_settings()
    d = StateDetector(lambda: s["options"])
    st = s["states"]
    snap = lambda t: set(d.snapshot(t, st))  # noqa: E731

    def full(**kw):
        data = payload(**{k: v for k, v in kw.items() if k in ("state", "round", "weapons", "steamid")})
        data["map"].update(kw.get("map", {}))
        data["player"]["match_stats"] = kw.get("ms", {"kills": 0, "assists": 0, "mvps": 0})
        return data

    d.update(full(weapons={"a": {"name": "weapon_knife", "type": "Knife", "state": "active"},
                           "b": {"name": "weapon_c4", "type": "C4", "state": "holstered"}}), now=1)
    assert {"knife_out", "carrying_bomb"} <= snap(1), snap(1)
    d.update(full(state={"armor": 0}, weapons={"a": {"name": "weapon_flashbang", "type": "Grenade",
                                                     "state": "active"}}), now=2)
    assert {"grenade_out", "no_armor"} <= snap(2), snap(2)
    for i, k in enumerate((1, 2, 3, 4, 5)):
        d.update(full(state={"round_kills": k}), now=3 + i)
    assert "ace" in snap(7.1)
    d.update(full(state={"round_kills": 0}), now=20)
    d.update(full(state={"round_kills": 0}, ms={"kills": 0, "assists": 1, "mvps": 1}), now=21)
    assert {"assist", "mvp"} <= snap(21.1), snap(21.1)
    d.update(full(state={"health": 0}), now=30)
    assert "death" in snap(30.1) and "dead" in snap(30.1)
    d.update(full(round={"phase": "live", "bomb": "planted"}), now=40)
    assert "bomb_critical" not in snap(60) and "bomb_critical" in snap(71)
    d.update(full(map={"mode": "competitive", "team_ct": {"score": 12}, "team_t": {"score": 5}}), now=80)
    assert "matchpoint" in snap(80)
    d.update(full(map={"phase": "intermission"}), now=81)
    assert "halftime" in snap(81)
    d.update(full(map={"phase": "gameover", "team_ct": {"score": 13}, "team_t": {"score": 5}}), now=82)
    assert "match_won" in snap(82.5)
    assert not st["knife_out"]["enabled"] and st["bomb_critical"]["enabled"]
    print("neue Zustände ok")


def test_engine():
    s = config.default_settings()
    d = StateDetector(lambda: s["options"])
    e = LightEngine(None, d, lambda: s)
    d.update(payload(state={"flashed": 255}), now=1)
    frame = e.compose(e.layers(1.0, s), 4, 1.0)
    assert frame == [(255, 255, 255)] * 4, frame
    d.update(payload(), now=10)  # Blitz (2.5 s) ist vorbei
    frame = e.compose(e.layers(10.0, s), 3, 1.0)
    assert frame[0] == (0, 0, 89), frame  # CT gedimmt wie im alten Bridge
    d.update(payload(team="T", round={"phase": "freezetime"}), now=11)
    frame = e.compose(e.layers(11.0, s), 2, 1.0)
    assert frame[0] == (0, 255, 0), frame  # Kaufphase: volle Teamfarbe T
    assert state_color(s["states"]["round_won"], s["states"], "CT") == (0, 0, 255)
    for eff in config.EFFECTS:
        st = dict(s["states"]["kill"], effect=eff)
        out = e.compose([(st, (10, 20, 30), 0.3, 1.0)], 8, 1.0)
        assert len(out) == 8 and all(len(c) == 3 for c in out)
    print("engine ok")


def test_flash_effect():
    from cs2local.effects import render
    full = render("flash", (255, 255, 255), 1.0, 0.3, 1, 2.5)[0]
    half = render("flash", (255, 255, 255), 1.0, 1.6, 1, 2.5)[0]
    gone = render("flash", (255, 255, 255), 1.0, 2.6, 1, 2.5)[0]
    assert full == (255, 255, 255) and 0 < half[0] < 255 and gone == (0, 0, 0), (full, half, gone)
    old = {"version": 2, "states": {"flashed": {"effect": "solid", "duration": 0}}}
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        config.SETTINGS_FILE = Path(tmp) / "s.json"
        config.SETTINGS_FILE.write_text(json.dumps(old))
        assert config.load_settings()["states"]["flashed"]["effect"] == "flash"  # alte Einstellung migriert
    print("Blitz ok")


def test_c4_beat():
    from cs2local.effects import c4_beeps, c4_level
    beeps = c4_beeps()
    gaps = [b - a for a, b in zip(beeps, beeps[1:])]
    assert abs(gaps[0] - 1.0) < 0.01, gaps[0]          # anfangs 1 Piep pro Sekunde
    assert all(g1 >= g2 - 1e-9 for g1, g2 in zip(gaps, gaps[1:]))  # wird nur schneller
    assert abs(gaps[-1] - 0.15) < 1e-6 and beeps[-1] < 40.0  # am Ende ~7 pro Sekunde
    assert c4_level(beeps[10] + 0.01) == 1.0 and c4_level(beeps[10] - 0.05) < 0.2  # an beim Piep, sonst dunkel
    # Alle Bomben-Ebenen laufen auf der Uhr ab dem Legen (auch „wäre tödlich“, das später beginnt)
    settings = config.default_settings()
    eng = LightEngine.__new__(LightEngine)
    eng.detector = type("D", (), {"team": "T", "snapshot": lambda self, now, st: {
        "bomb_planted": (12.34, 1.0), "bomb_lethal": (2.0, 1.0)}})()
    layers = eng.layers(100.0, settings)
    ts = {cfg["_id"] if "_id" in cfg else cfg["name"]: t for cfg, _c, t, _a in layers}
    assert all(abs(t - 12.34) < 1e-9 for t in ts.values()), ts
    # Alte Einstellungen (Blinken) werden auf den C4-Takt umgestellt, eigene Effekte bleiben
    old = {"version": 3, "states": {"bomb_planted": {"effect": "blink", "color": [255, 0, 0]},
                                    "bomb_lethal": {"effect": "pulse"}, "bomb_critical": {"effect": "solid"}}}
    with tempfile.TemporaryDirectory() as tmp:
        config.SETTINGS_FILE = Path(tmp) / "s.json"
        config.SETTINGS_FILE.write_text(json.dumps(old))
        st = config.load_settings()["states"]
    assert st["bomb_planted"]["effect"] == "c4" and st["bomb_lethal"]["effect"] == "c4"
    assert st["bomb_critical"]["effect"] == "solid"
    print("C4-Takt ok")


def test_settings_roundtrip():
    s = config.default_settings()
    s["states"]["kill"]["color"] = [1, 2, 3]
    s["devices"] = ["A::B"]
    with tempfile.TemporaryDirectory() as tmp:
        config.SETTINGS_FILE = Path(tmp) / "s.json"
        config.save_settings(s)
        loaded = config.load_settings()
    assert loaded["states"]["kill"]["color"] == [1, 2, 3] and loaded["devices"] == ["A::B"]
    print("settings ok")


def test_setup():
    vdf = ('"libraryfolders"\n{\n "0"\n {\n  "path"  "C:\\\\Program Files (x86)\\\\Steam"\n }\n'
           ' "1"\n {\n  "path"  "D:\\\\SteamLibrary"\n }\n}')
    assert [str(p) for p in parse_library_folders(vdf)] == ["C:\\Program Files (x86)\\Steam", "D:\\SteamLibrary"]
    with tempfile.TemporaryDirectory() as tmp:
        cs2 = Path(tmp) / "Counter-Strike Global Offensive"
        cfg = cs2 / "game" / "csgo" / "cfg"
        cfg.mkdir(parents=True)
        (cfg / "gamestate_integration_homeassistant.cfg").write_text("x")
        assert normalize_cs2_dir(cfg) == cs2
        path, changed = write_gsi_config(cs2, 3002, "abc")
        assert changed and '"token" "abc"' in path.read_text()
        assert write_gsi_config(cs2, 3002, "abc")[1] is False
        assert other_gsi_files(cs2) == ["gamestate_integration_homeassistant.cfg"]
    print("setup ok")


def test_server():
    got = []
    srv = GSIServer("tok", got.append)
    port = srv.start(38410)
    for token in ("falsch", "tok"):
        body = json.dumps({"auth": {"token": token}, "map": {"name": "x"}}).encode()
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}", body), timeout=3).read()
    srv.stop()
    assert len(got) == 1 and got[0]["map"]["name"] == "x"
    print("server ok")


if __name__ == "__main__":
    test_states()
    test_new_states()
    test_engine()
    test_flash_effect()
    test_c4_beat()
    test_settings_roundtrip()
    test_setup()
    test_server()
    print("ALLE TESTS OK")
