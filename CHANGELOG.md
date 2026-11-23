# Changelog
## 2.0.0 – CS2 Local Claude
- neue lokale Version im Ordner `cs2-local-claude/`, komplett neu gebaut mit Claude
- eine einzige EXE (`CS2LocalClaude.exe`) mit Adminabfrage per Doppelklick, nichts zu installieren
- eingebaute RGB-Engine (OpenRGB 1.1) erkennt alle RGB-Geräte automatisch, läuft unsichtbar nur für die Sitzung
- PawnIO-Treiber für RGB-Arbeitsspeicher eingebaut: wird geprüft und nach Zustimmung installiert
- erkennt störende RGB-Programme (Logitech G HUB, Gigabyte RGB Fusion, iCUE …) und schliesst sie auf Wunsch
- findet CS2 automatisch und schreibt die GSI-Config selbst
- moderne Oberfläche mit 22 einstellbaren Situationen, Vorschau und Start-Knopf
- neue Zustände: Kill, Headshot, Nachladen, Munition knapp, Aufwärmphase, „Bombe wäre tödlich“ (`health_c4_preview`)
- merkt sich die letzten Einstellungen und stellt beim Beenden die vorherigen Farben wieder her
- GitHub Actions baut und testet die EXE automatisch und veröffentlicht sie als Release
- `local_pc/` bleibt als Altversion 0.3.x bestehen

## 0.3.15
- finalized combined HA + local setup
- fixed HA package mode behavior
- fixed exploded hold until freezetime
- fixed round-end winner colors
- fixed HA burning behavior
- updated addon build files
- updated docs for File Editor, package install, local install, hybrid install, and autostart
## 0.3.14
- finalized Home Assistant package mode setup
- added idiot-proof installation guidance for Home Assistant, local-only, and hybrid setups
- added repository metadata for Home Assistant add-on repository integration
- fixed add-on build files:
  - Dockerfile
  - run.sh
  - requirements.txt
- local bridge:
  - bomb blink refined
  - flash timing configurable
  - winner hold added
  - exploded stays red
  - defused blue handling kept
  - smoke / burning / damage / HP effects included
- Home Assistant package/manual YAML:
  - switched to `light.cs2gsi` group-based setup
  - winner hold corrected
  - exploded now holds until freezetime
  - burning package behavior fixed
- documentation expanded:
  - File editor / package installation
  - autostart on Windows
  - GitHub update instructions
  - HA-only / local-only / hybrid setup paths

## 0.3.13
- fixed Home Assistant add-on install with Python virtual environment
- improved repository structure for new `CS2GSI-HA-LOCAL` repo

## 0.3.12
- initial combined HA + local bundle
- added round-end winner hold
- added local bridge package separation
