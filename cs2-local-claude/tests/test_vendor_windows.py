"""Windows-Test: Hersteller-Software erkennen, pausieren und mit gleicher Befehlszeile wieder starten.

Startet eine Kopie von ping.exe aus einem Ordner „…\\GIGABYTE\\Control Center\\“ (so wie GCC installiert ist),
pausiert sie über das Tool und prüft, dass sie beim „Schliessen“ wieder mit denselben Parametern läuft.
"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2local import vendor_apps  # noqa: E402

logging.basicConfig(level=logging.INFO)

root = Path(tempfile.mkdtemp()) / "GIGABYTE" / "Control Center"
root.mkdir(parents=True)
fake = root / "GCC_Test.exe"
shutil.copy(Path(os.environ["WINDIR"]) / "System32" / "PING.EXE", fake)
fake = Path(os.path.realpath(fake))  # lange Pfadnamen (Temp-Ordner kann RUNNER~1 heissen)
vendor_apps.PENDING_FILE = Path(tempfile.mkdtemp()) / "restart.json"

proc = subprocess.Popen([str(fake), "-n", "120", "127.0.0.1"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW)
time.sleep(1.5)
assert proc.poll() is None, "Testprogramm läuft nicht"

import winreg  # noqa: E402

KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CS2LocalTestICUE"
with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:  # nur „installiert“, läuft nicht
    winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "iCUE Testeintrag")
    winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "Corsair")
try:
    found = vendor_apps.scan()
finally:
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY)
icue = found.get("Corsair iCUE")
assert icue and icue["installed"], "installierte Software (Registry) nicht erkannt"
print("Installiert erkannt: Corsair iCUE (läuft:", bool(icue["processes"] or icue["services"]), ")")
assert "Corsair iCUE" not in vendor_apps.running({"Corsair iCUE": icue}) or icue["processes"] or icue["services"]
print("Gefunden:", {k: [p["name"] for p in v["processes"]] for k, v in found.items()})
gigabyte = found.get("Gigabyte Control Center / RGB Fusion")
assert gigabyte and any(p["path"].lower() == str(fake).lower() for p in gigabyte["processes"]), "GCC-Test nicht erkannt"

only_fake = {"Gigabyte Control Center / RGB Fusion": {
    "services": [], "processes": [p for p in gigabyte["processes"] if p["path"].lower() == str(fake).lower()]}}
failed = vendor_apps.pause(only_fake)
assert not failed, failed
time.sleep(1.0)
assert proc.poll() is not None, "Programm wurde nicht beendet"
assert vendor_apps.PENDING_FILE.exists(), "Neustart-Liste nicht gespeichert (Absturzschutz)"
print("Pausiert und Neustart-Liste gespeichert")

errors = vendor_apps.resume()
assert not errors, errors
time.sleep(2.0)
again = vendor_apps.scan().get("Gigabyte Control Center / RGB Fusion", {"processes": []})["processes"]
restarted = [p for p in again if p["path"].lower() == str(fake).lower()]
assert restarted, "Programm wurde nicht wieder gestartet"
assert "-n 120" in restarted[0]["cmd"], f"Parameter verloren: {restarted[0]['cmd']}"
assert not vendor_apps.PENDING_FILE.exists()
print("Mit gleicher Befehlszeile wieder gestartet:", restarted[0]["cmd"])
for p in restarted:
    subprocess.run(["taskkill", "/F", "/PID", str(p["pid"])], capture_output=True)
print("HERSTELLER-SOFTWARE OK")
