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
from .i18n import set_language, tr


def setup_logging() -> None:
    handlers: list = [logging.StreamHandler()] if sys.stderr else []  # EXE ohne Konsole: kein stderr
    try:
        handlers.insert(0, logging.FileHandler(config.LOG_FILE, mode="w", encoding="utf-8"))
    except OSError:
        pass  # z. B. schreibgeschützter Ordner: dann nur Konsole
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


def choose_settings(last: dict | None, autostart: bool = False) -> dict:
    settings = config.default_settings()
    settings["language"], settings["language_chosen"] = (last or settings)["language"], True
    if not last:
        return settings
    if autostart:  # Windows-Autostart: ohne Rückfrage mit der letzten Sitzung
        return last
    box = QMessageBox()
    box.setWindowTitle(config.APP_NAME)
    box.setText(tr("<b>Letzte Einstellungen übernehmen?</b>"))
    box.setInformativeText(tr("Geräteauswahl und Effekte deiner letzten Sitzung wurden gefunden."))
    take = box.addButton(tr("Übernehmen"), QMessageBox.AcceptRole)
    box.addButton(tr("Neu beginnen"), QMessageBox.RejectRole)
    box.setDefaultButton(take)
    box.exec()
    if box.clickedButton() is take:
        return last
    for key in ("cs2_path", "gsi_token", "zone_sizes", "zone_layout", "pawnio_declined", "device_methods", "engine",
                "language", "language_chosen"):  # technische Werte behalten
        settings[key] = last.get(key, settings[key])
    for key in ("gsi_port", "openrgb_port"):
        settings["options"][key] = last["options"][key]
    return settings


def selftest() -> int:
    """Prüft die fertige EXE ohne Oberfläche: Bausteine vorhanden, RGB-Engine startet und antwortet."""
    from .rgb_engine import RGBEngine
    from .system import pawnio_setup_available

    log = logging.getLogger("selftest")
    lines = [f"{config.APP_NAME} {config.VERSION}", tr("Bausteine: {v0}", v0=config.resource_dir())]
    ok = True
    exe = RGBEngine(6799).find_exe()
    lines.append(tr("OpenRGB.exe: {v0}", v0=exe))
    ok &= exe is not None
    lines.append(tr("PawnIO-Setup: {v0}", v0=pawnio_setup_available()))
    lines.append(tr("Entwicklungsversion eingebaut: {v0}", v0=RGBEngine.dev_available()))
    ok &= pawnio_setup_available()
    engine = RGBEngine(6799)
    try:
        engine.start(progress=lambda m: lines.append(m))
        lines.append(tr("RGB-Engine verbunden, Zonen: {v0}", v0=len(engine.zones())))
    except Exception as exc:  # noqa: BLE001
        lines.append(tr("RGB-Engine FEHLER: {v0}", v0=exc))
        ok = False
    finally:
        engine.shutdown()
    lines.append(tr("SELFTEST OK") if ok else tr("SELFTEST FEHLGESCHLAGEN"))
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
    last = config.load_settings()
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)
    language = (last or {}).get("language", "en")
    if not (last or {}).get("language_chosen"):  # erster Start: Sprache wählen
        from .ui.settings_dialog import LanguageDialog
        dlg = LanguageDialog(language)
        dlg.exec()
        language = dlg.code
        if last:
            last["language"], last["language_chosen"] = language, True
    set_language(language)

    if os.name == "nt" and not is_admin():
        answer = QMessageBox.question(
            None, config.APP_NAME,
            tr("Das Tool läuft ohne Adminrechte.\n\nDie brauchen wir, um Arbeitsspeicher- und Mainboard-LEDs anzusprechen. Mit Adminrechten neu starten?"))
        if answer == QMessageBox.Yes and relaunch_as_admin():
            return 0

    try:
        settings = choose_settings(last, autostart="--autostart" in sys.argv)
        settings["language"], settings["language_chosen"] = language, True
        config.save_settings(settings)
        window = MainWindow(settings)
    except Exception:  # noqa: BLE001
        log.exception("Start fehlgeschlagen")
        QMessageBox.critical(None, config.APP_NAME, tr("Das Tool konnte nicht starten. Details: {v0}", v0=config.LOG_FILE))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
