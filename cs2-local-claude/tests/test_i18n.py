"""Prüft die Übersetzungen: jeder Text im Code hat Englisch und Portugiesisch, Platzhalter stimmen.

python tests/test_i18n.py
"""
import ast
import re
import string
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from cs2local import config, i18n  # noqa: E402
from cs2local.i18n_strings import TRANSLATIONS  # noqa: E402
from cs2local.sdk_client import DEVICE_TYPES  # noqa: E402


def collect_keys() -> list:
    keys = []

    def add(k):
        if k and k not in keys:
            keys.append(k)

    for f in sorted((SRC / "cs2local").rglob("*.py")):
        if f.name.startswith("i18n"):
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                add(node.args[0].value)
    for s in config.default_settings()["states"].values():
        add(s["name"])
        add(s["desc"])
    for v in config.EFFECTS.values():
        add(v)
    for title, text, _ids, opts in config.CATEGORIES:
        add(title)
        add(text)
        for o in opts:
            add(o[1])
            add(o[2])
    for name, *_ in config.HARDWARE_PRESETS:
        add(name)
    for v in DEVICE_TYPES.values():
        add(v)
    from cs2local.rgb_engine import RGBEngine
    for _marker, _value, label in RGBEngine._PHASES:  # noqa: SLF001
        add(label)
    add("Suche läuft")
    return keys


def fields(text: str) -> set:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_complete():
    keys = collect_keys()
    assert len(keys) > 300, len(keys)
    for lang in ("en", "pt"):
        table = TRANSLATIONS[lang]
        missing = [k for k in keys if k not in table]
        assert not missing, f"{lang}: {len(missing)} fehlen, z. B. {missing[:5]}"
        for k in keys:
            assert fields(table[k]) == fields(k), f"{lang}: Platzhalter passen nicht: {k!r}"
            assert table[k].startswith(" ") == k.startswith(" "), f"{lang}: Leerzeichen am Anfang: {k!r}"
            assert table[k].count("\n") == k.count("\n"), f"{lang}: Zeilenumbrüche: {k!r}"
    stale = [k for k in TRANSLATIONS["en"] if k not in keys]
    assert not stale, f"Übersetzungen ohne Text im Code: {stale[:5]}"
    print(f"i18n vollständig: {len(keys)} Texte")


def test_no_german_left_in_english():
    umlaut = re.compile(r"[äöüÄÖÜß]")
    bad = [v for v in TRANSLATIONS["en"].values() if umlaut.search(v)]
    assert not bad, bad[:5]
    print("Englisch ohne Umlaute ok")


def test_tr():
    i18n.set_language("en")
    assert i18n.tr("Bereit. {v0} Geräte mit {v1} Zonen erkannt.", v0=3, v1=7) == "Ready. 3 devices with 7 zones detected."
    i18n.set_language("pt")
    assert i18n.tr("Sprache") == "Idioma"
    i18n.set_language("de")
    assert i18n.tr("Sprache") == "Sprache"
    i18n.set_language("xx")  # Unbekannt: Englisch
    assert i18n.LANG == "en"
    print("tr ok")


if __name__ == "__main__":
    test_complete()
    test_no_german_left_in_english()
    test_tr()
    print("ALLE TESTS OK")
