"""Sprachen: Englisch (Standard), Deutsch, Portugiesisch (Brasilien).

Die Texte im Code sind deutsch geschrieben und dienen als Schlüssel. tr() liefert die Übersetzung für die
gewählte Sprache; fehlt eine, erscheint der deutsche Text (nie ein leeres Feld).
"""
from __future__ import annotations

LANGUAGES = {"en": "English", "de": "Deutsch", "pt": "Português (Brasil)"}
LANG = "en"


def set_language(code: str) -> None:
    global LANG
    LANG = code if code in LANGUAGES else "en"


def tr(text: str, **kw) -> str:
    if LANG != "de":
        from .i18n_strings import TRANSLATIONS
        text = TRANSLATIONS.get(LANG, {}).get(text, text)
    return text.format(**kw) if kw else text
