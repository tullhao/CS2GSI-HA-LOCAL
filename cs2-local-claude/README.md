# CS2 Local Claude 2.0

**Neue lokale Version von CS2GSI-HA-LOCAL, gebaut mit Claude.** Deine RGB-Beleuchtung reagiert live auf
Counter-Strike 2. Alles steckt in einer einzigen EXE.

## Für Spieler
1. Unter [Releases](https://github.com/tullhao/CS2GSI-HA-LOCAL/releases) die neueste `CS2LocalClaude.exe` herunterladen.
2. Doppelklick, Windows-Abfrage („Adminrechte“) bestätigen.
3. Das Tool prüft alles selbst:
   - **Counter-Strike 2** wird gefunden, die Config wird automatisch angelegt.
   - **Treiber PawnIO** (nur für RGB-Arbeitsspeicher): Fehlt er, erklärt das Tool, wofür er gebraucht wird, und installiert ihn nach deiner Zustimmung. Er ist in der EXE enthalten.
   - **Störende RGB-Programme** (z. B. Logitech G HUB, Gigabyte RGB Fusion) werden erkannt und auf Wunsch für diese Sitzung geschlossen.
   - **RGB-Geräte** werden automatisch erkannt.
4. **Geräte**: Zonen anhaken, „Auswahl testen“. Bei ARGB-Headern die Anzahl LEDs eintragen.
5. **Effekte**: Farben und Effekte nach Wunsch.
6. **Live**: START drücken und spielen.

Beim Schliessen wird alles beendet und deine alten Farben kommen zurück. Beim nächsten Start fragt das Tool,
ob es die letzten Einstellungen übernehmen soll (`cs2local_settings.json` neben der EXE).

**Nichts wird dauerhaft installiert**, ausser du stimmst dem PawnIO-Treiber zu. Die CS2-Config
`game\csgo\cfg\gamestate_integration_cs2localclaude.cfg` kannst du jederzeit löschen.

### Home Assistant
Läuft unabhängig weiter. CS2 schickt die Daten an alle Configs gleichzeitig, deine
`gamestate_integration_homeassistant.cfg` bleibt also einfach liegen.

### Welche Geräte?
Alles, was OpenRGB 1.1 unterstützt: Mainboards (z. B. Gigabyte X870 über RGB Fusion 2 USB), ARGB-Header,
RGB-Arbeitsspeicher, Grafikkarten, Tastaturen und Mäuse von Logitech, Corsair, Razer, SteelSeries, HyperX und
vielen mehr. Geräte ohne RGB-LEDs (z. B. Logitech PRO X SUPERLIGHT 2) erscheinen nicht.

## Wie es funktioniert
| Teil | Aufgabe |
|---|---|
| `src/cs2local/app.py` | Start, Adminrechte, „Letzte Einstellungen übernehmen?“, `--selftest` |
| `src/cs2local/cs2_setup.py` | CS2 über Registry und `libraryfolders.vdf` finden, Config schreiben |
| `src/cs2local/gsi_server.py` | Empfängt die CS2-Daten nur auf 127.0.0.1, prüft das Token |
| `src/cs2local/states.py` | CS2-Daten → aktive Zustände und Ereignisse |
| `src/cs2local/effects.py` | Effekte: fest, blinken, pulsieren, flackern, Lauflicht, ausblenden |
| `src/cs2local/engine.py` | Ebenen nach Priorität mischen, Teamfarben, Bombe beschleunigt |
| `src/cs2local/rgb_engine.py` | Eingebauter OpenRGB-Kern: unsichtbar starten, Geräte erkennen, steuern, wiederherstellen |
| `src/cs2local/system.py` | Adminrechte, PawnIO prüfen/installieren, störende Programme |
| `src/cs2local/ui/` | Oberfläche (PySide6, dunkles Design) |

Die Geräteerkennung übernimmt der OpenRGB-Kern, der unverändert in die EXE gepackt und nur für die Sitzung
gestartet wird. Er bringt die Protokolle für hunderte Geräte mit, die in eigener Neuentwicklung nie so
zuverlässig wären.

## Selbst bauen
Die EXE baut GitHub Actions automatisch (`.github/workflows/cs2-local-claude.yml`) und testet sie dabei:
Kernlogik, Oberfläche, Start der RGB-Engine unter Windows und einen Selbsttest der fertigen EXE.
Ein Tag `v*` veröffentlicht sie als Release.

Lokal unter Windows mit Python 3.12: `build.bat` doppelklicken. Ergebnis: `dist\CS2LocalClaude.exe`.

## Lizenz
GPL-2.0 (siehe `LICENSE`). Enthält OpenRGB 1.1 (GPL-2.0) und das PawnIO-Setup von namazso unverändert.
