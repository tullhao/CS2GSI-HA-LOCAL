## CS2 Local Claude 2.0 – die neue lokale Version

Komplett neu gebaut (mit Claude). Ersetzt den alten `local_pc`-Bridge.

**Eine Datei, Doppelklick, fertig.** `CS2LocalClaude.exe` herunterladen, starten, Windows-Abfrage bestätigen.
Nichts muss installiert oder heruntergeladen werden. Python und OpenRGB braucht es nicht mehr.

### Was das Tool selbst erledigt
- findet Counter-Strike 2 und legt die Game-State-Config automatisch an
- startet die eingebaute RGB-Engine unsichtbar und erkennt alle RGB-Geräte (Mainboard, ARGB-Header, RAM, Grafikkarte, Logitech, Corsair, Razer …)
- prüft, ob der Treiber PawnIO für RGB-Arbeitsspeicher da ist, und installiert ihn nach deiner Zustimmung (ist in der EXE enthalten)
- erkennt Programme wie Logitech G HUB oder Gigabyte RGB Fusion, die die Erkennung blockieren, und schliesst sie auf Wunsch für diese Sitzung
- stellt beim Beenden deine vorherigen Farben wieder her und merkt sich deine Einstellungen

### Neu
- moderne Oberfläche: Übersicht, Geräte, Effekte, Live mit grossem Start-Knopf
- 22 Situationen frei einstellbar: Farbe oder Teamfarbe, Effekt, Tempo, Dauer, Helligkeit, Priorität, Vorschau
- neue Zustände: Kill, Headshot, Nachladen, Munition knapp, Runde verloren, Aufwärmphase und **Bombe wäre tödlich** (neues CS2-Feld `health_c4_preview`)
- Standardfarben wie bisher: CT blau, T grün, Bombe blinkt immer schneller, Flash weiss, Explosion rot bis zur nächsten Runde

### Hinweise
- Home Assistant läuft unabhängig weiter: CS2 bedient mehrere Configs gleichzeitig.
- Windows SmartScreen kann bei neuen, unsignierten EXE-Dateien warnen: „Weitere Informationen“ → „Trotzdem ausführen“.
- Enthält OpenRGB 1.1 (GPL-2.0) und das PawnIO-Setup unverändert. Quellen in `licenses/SOURCES.txt`.
