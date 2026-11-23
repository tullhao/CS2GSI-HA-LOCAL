"""Einstiegspunkt: Logging, Adminrechte, letzte Einstellungen, Hauptfenster."""
from __future__ import annotations

import logging
import os
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from . import config
from .system import is_admin, relaunch_as_admin
from .ui.main_window import MainWindow
from .ui.theme import STYLE


def setup_logging() -> None:
    handlers: list = [logging.StreamHandler()] if sys.stderr else []  # EXE ohne Konsole: kein stderr
    try:
        handlers.insert(0, logging.FileHandler(config.LOG_FILE, mode="w", encoding="utf-8"))
    except OSError:
        pass  # z. B. schreibgeschützter Ordner: dann nur Konsole
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


def choose_settings() -> dict:
    last = config.load_settings()
    settings = config.default_settings()
    if not last:
        return settings
    box = QMessageBox()
    box.setWindowTitle(config.APP_NAME)
    box.setText("<b>Letzte Einstellungen übernehmen?</b>")
    box.setInformativeText("Geräteauswahl und Effekte deiner letzten Sitzung wurden gefunden.")
    take = box.addButton("Übernehmen", QMessageBox.AcceptRole)
    box.addButton("Neu beginnen", QMessageBox.RejectRole)
    box.setDefaultButton(take)
    box.exec()
    if box.clickedButton() is take:
        return last
    for key in ("cs2_path", "gsi_token", "zone_sizes", "zone_layout", "pawnio_declined", "device_methods"):  # technische Werte behalten
        settings[key] = last.get(key, settings[key])
    for key in ("gsi_port", "openrgb_port"):
        settings["options"][key] = last["options"][key]
    return settings


def selftest() -> int:
    """Prüft die fertige EXE ohne Oberfläche: Bausteine vorhanden, RGB-Engine startet und antwortet."""
    from .rgb_engine import RGBEngine
    from .system import pawnio_setup_available

    log = logging.getLogger("selftest")
    lines = [f"{config.APP_NAME} {config.VERSION}", f"Bausteine: {config.resource_dir()}"]
    ok = True
    exe = RGBEngine.find_exe()
    lines.append(f"OpenRGB.exe: {exe}")
    ok &= exe is not None
    lines.append(f"PawnIO-Setup: {pawnio_setup_available()}")
    ok &= pawnio_setup_available()
    engine = RGBEngine(6799)
    try:
        engine.start(progress=lambda m: lines.append(m))
        lines.append(f"RGB-Engine verbunden, Zonen: {len(engine.zones())}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"RGB-Engine FEHLER: {exc}")
        ok = False
    finally:
        engine.shutdown()
    lines.append("SELFTEST OK" if ok else "SELFTEST FEHLGESCHLAGEN")
    for line in lines:
        log.info(line)
    try:
        (config.app_dir() / "cs2local_selftest.txt").write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1


def main() -> int:
    setup_logging()
    log = logging.getLogger(__name__)
    log.info("%s %s startet", config.APP_NAME, config.VERSION)
    if "--selftest" in sys.argv:
        return selftest()
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)

    if os.name == "nt" and not is_admin():
        answer = QMessageBox.question(
            None, config.APP_NAME,
            "Das Tool läuft ohne Adminrechte.\n\nDie brauchen wir, um Arbeitsspeicher- und Mainboard-LEDs "
            "anzusprechen. Mit Adminrechten neu starten?")
        if answer == QMessageBox.Yes and relaunch_as_admin():
            return 0

    try:
        window = MainWindow(choose_settings())
    except Exception:  # noqa: BLE001
        log.exception("Start fehlgeschlagen")
        QMessageBox.critical(None, config.APP_NAME, f"Das Tool konnte nicht starten. Details: {config.LOG_FILE}")
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
