"""Lesende Diagnose; keine vollständigen Gerätekennungen im Ergebnis."""
import platform
import json
import os
import shutil
import subprocess
from .session import ROOT, select_local_xcode
import sys


def run(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def doctor():
    select_local_xcode()
    good = platform.system() == "Darwin"
    print(f"{'vorhanden' if good else 'fehlt'}: lokaler macOS-Host ({platform.machine()})")
    _, version = run(["sw_vers", "-productVersion"])
    print(f"macOS: {version or 'nicht ermittelbar'}; frei: {shutil.disk_usage(ROOT).free // 2**30} GiB")
    code, version = run(["xcodebuild", "-version"])
    xcode = code == 0 and version.startswith("Xcode ")
    print(f"{'vorhanden' if xcode else 'fehlt'}: vollständiges aktives Xcode" + (f" ({version.replace(chr(10), ', ')})" if xcode else ""))
    _, path = run(["xcode-select", "-p"])
    print(f"Systemweiter Developer-Pfad: {path or 'nicht verfügbar'}")
    print(f"Projekt-Auswahl DEVELOPER_DIR: {os.environ.get('DEVELOPER_DIR', 'nicht gesetzt')}")
    if xcode:
        code, _ = run(["xcodebuild", "-checkFirstLaunchStatus"])
        print(f"{'vorhanden' if code == 0 else 'manuelle Aktion erforderlich'}: Xcode-Erstinitialisierung")
        good &= code == 0
    good &= xcode
    for binary in ("node", "npm", "python3"):
        code, output = run([binary, "--version"])
        print(f"{'vorhanden' if code == 0 else 'fehlt'}: {binary} {output}")
        good &= code == 0
    print(f"receiptbot-Interpreter: Python {platform.python_version()} ({'isoliert' if sys.prefix != sys.base_prefix else 'keine venv'})")
    code, _ = run([str(ROOT / "node_modules/.bin/appium"), "--version"])
    print(f"{'vorhanden' if code == 0 else 'fehlt'}: projektlokales Appium")
    good &= code == 0
    driver_file = ROOT / "node_modules/appium-xcuitest-driver/package.json"
    if driver_file.is_file():
        print("vorhanden: projektlokales XCUITest " + json.loads(driver_file.read_text())["version"])
    else:
        print("fehlt: projektlokaler XCUITest-Treiber")
        good = False
    code, usb = run(["ioreg", "-p", "IOUSB", "-l"])
    phone = code == 0 and "iPhone" in usb
    print(f"{'vorhanden' if phone else 'manuelle Aktion erforderlich'}: iPhone im USB-Baum")
    if xcode:
        code, raw = run(["xcrun", "devicectl", "list", "devices", "--json-output", "-", "--timeout", "15"])
        try:
            devices = json.loads(raw).get("result", {}).get("devices", []) if code == 0 else []
            print(f"Xcode-Geräte: {len(devices)} (keine Namen oder Kennungen ausgegeben)")
            # Die Liste kann nach Neustarts veraltet sein. Nur das konfigurierte Gerät aktiv auffrischen.
            config_path = ROOT / 'config.local.json'
            if config_path.is_file():
                config = json.loads(config_path.read_text())
                if config.get('udid'):
                    detail_code, detail_raw = run(['xcrun', 'devicectl', 'device', 'info', 'details',
                                                  '--device', config['udid'], '--json-output', '-', '--timeout', '15'])
                    if detail_code == 0:
                        detail = json.loads(detail_raw).get('result', {})
                        devices = [detail.get('device', detail)]
                    else:
                        print('Aktive Geräteabfrage fehlgeschlagen; Listenangaben können veraltet sein.')
                        good = False
            for device in devices:
                h = device.get('hardwareProperties', {})
                d = device.get('deviceProperties', {})
                c = device.get('connectionProperties', {})
                print(f"Modell: {h.get('marketingName', 'unbekannt')}; iOS: {d.get('osVersionNumber', 'unbekannt')}; "
                      f"Pairing: {c.get('pairingState', 'unbekannt')}; Verbindung: {c.get('transportType', 'unbekannt')}; "
                      f"Entwicklermodus: {d.get('developerModeStatus', 'unbekannt')}")
                good &= d.get('developerModeStatus') == 'enabled'
            good &= bool(devices)
        except (ValueError, TypeError, AttributeError):
            print("Geräteinformationen nicht auswertbar; Rohdaten unterdrückt.")
            good = False
    print("Diese Diagnose startet keine WDA-Session; belegte Gerätetests stehen in STATUS.md.")
    print("Kaufland-iCloud-Einzelexport am Referenzgerät verifiziert. dm/Lidl/Rossmann noch nicht implementiert; aktuelle Abnahme siehe STATUS.md.")
    return 0 if good and phone else 2
