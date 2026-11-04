"""Lesende Startprüfung; kein WDA-Start, keine UI-Ausgabe, keine Gerätecodes."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import socket
import sqlite3
import subprocess
import time
from .session import ROOT, capabilities, select_local_xcode
from .icloud import transport_settings


def device_status(config):
    """Aktives konfiguriertes Gerät, kein Vertrauen auf eine passive Geräteliste.

    Unbekannte JSON-Formate sperren den Start. passcodeRequired=false ersetzt
    nicht die zusätzliche WDA-is_locked-Prüfung unmittelbar vor Bedienaktionen.
    """
    select_local_xcode()
    try:
        result = subprocess.run(['xcrun', 'devicectl', 'device', 'info', 'details',
            '--device', config['udid'], '--json-output', '-', '--timeout', '8'],
            capture_output=True, text=True, timeout=10)
        if result.returncode:
            return False, 'iPhone per USB verbinden und entsperren.'
        info = json.loads(result.stdout).get('result', {})
        info = info.get('device', info)
        connection = info.get('connectionProperties', {})
        properties = info.get('deviceProperties', {})
        if connection.get('transportType') != 'wired':
            return False, 'USB-Verbindung noch nicht bestätigt; Netzwerk/Cache genügt nicht.'
        if connection.get('pairingState') != 'paired':
            return False, 'Vertrauen zwischen iPhone und Mac selbst bestätigen.'
        if properties.get('developerModeStatus') != 'enabled':
            return False, 'Entwicklermodus muss am iPhone eingeschaltet sein.'
        result = subprocess.run(['xcrun', 'devicectl', 'device', 'info', 'lockState',
            '--device', config['udid'], '--json-output', '-', '--timeout', '8'],
            capture_output=True, text=True, timeout=10)
        if result.returncode:
            return False, 'Sperrstatus noch nicht lesbar; iPhone selbst entsperren.'
        state = json.loads(result.stdout).get('result', {})
        required = state.get('passcodeRequired')
        if required is True:
            return False, 'iPhone selbst entsperren; Gerätecode bleibt ausschließlich bei dir.'
        if required is not False:
            return False, 'Sperrstatusformat unbekannt; vor dem Export lokal prüfen.'
        return True, 'USB/Pairing/Entwicklermodus bestätigt, kein Gerätecode angefordert. WDA prüft die Sperre zusätzlich.'
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, AttributeError):
        return False, 'Gerät noch nicht zuverlässig abfragbar; USB-Verbindung und Entsperrung prüfen.'


def profile_status(config, root):
    if not config.get('use_prebuilt_wda'):
        return True, 'WDA wird durch die vorhandene Session-Konfiguration vorbereitet.'
    products = root / 'data/wda/DerivedData/Build/Products'
    profiles = list(products.glob('*/WebDriverAgentRunner-Runner.app/embedded.mobileprovision'))
    if len(profiles) != 1:
        return False, 'WDA-Provisioning nicht eindeutig vorhanden; lokalen WDA-Build prüfen.'
    try:
        result = subprocess.run(['security', 'cms', '-D', '-i', str(profiles[0])],
                                capture_output=True, timeout=8)
        if result.returncode:
            return False, 'WDA-Provisioning konnte nicht gelesen werden; keine Rohdaten ausgegeben.'
        profile = plistlib.loads(result.stdout)
        expiration = profile.get('ExpirationDate')
        if not isinstance(expiration, datetime):
            return False, 'WDA-Profil enthält kein lesbares Ablaufdatum.'
        remaining = (expiration.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return False, 'Kostenloses WDA-Provisioning abgelaufen; scripts/build_wda.py erneut ausführen.'
        return True, 'Vorhandenes WDA-Provisioning noch gültig (Restlaufzeit rund ' + str(max(1, int(remaining / 3600))) + ' Stunden).'
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.TimeoutExpired):
        return False, 'Lokales WDA-Profil konnte nicht geprüft werden.'


def local_checks(config, root=None):
    root = Path(root) if root else ROOT
    select_local_xcode()
    capabilities(config, 'kaufland')
    checks = []
    checks.append((platform.system() == 'Darwin', 'Lokaler macOS-Host erforderlich.'))
    checks.append((Path('/Applications/Xcode.app/Contents/Developer').is_dir(), 'Vollständiges Projekt-Xcode vorhanden.'))
    checks.append((bool(shutil.which('node')), 'Node im Prozesspfad vorhanden.'))
    checks.append(((root / 'node_modules/.bin/appium').is_file(), 'Projekt-Appium vorhanden.'))
    checks.append(((root / 'node_modules/appium-xcuitest-driver/package.json').is_file(), 'Projekt-XCUITest vorhanden.'))
    with socket.socket() as sock:
        checks.append((sock.connect_ex(('127.0.0.1', 4723)) != 0, 'Appium-Port 4723 muss vor dem eigenen Start frei sein.'))
    kind, directory, _ = transport_settings(config)
    checks.append((directory.is_dir() and os.access(directory, os.R_OK), 'Gewählter Eingangsordner lesbar: ' + kind + '.'))
    checks.append(profile_status(config, root))
    database = root / 'data/exports.sqlite3'
    if database.exists():
        try:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
                count = db.execute("SELECT count(*) FROM transfers WHERE merchant='kaufland' AND state IN ('sending','received')").fetchone()[0]
            checks.append((True, 'Ausstehende Transfers: ' + str(count) + '; sie werden vor erneutem Speichern fortgesetzt.'))
        except sqlite3.Error:
            checks.append((False, 'Bestehende Transferdatenbank zuerst prüfen; keine Änderung vorgenommen.'))
    return checks


def ready(config, wait_seconds=0):
    if not 0 <= wait_seconds <= 3600:
        raise ValueError('Wartezeit muss zwischen 0 und 3600 Sekunden liegen.')
    checks = local_checks(config)
    for passed, message in checks:
        print(('bereit: ' if passed else 'fehlt: ') + message, flush=True)
    if not all(passed for passed, _ in checks):
        return 2
    deadline = time.monotonic() + wait_seconds
    previous = None
    while True:
        passed, message = device_status(config)
        if message != previous:
            print(('bereit: ' if passed else 'warte: ') + message, flush=True)
            previous = message
        if passed:
            print('Startprüfung bestanden; Auto-Lock für den Lauf auf Nie. Kein UI-/Exportnachweis durch diese Prüfung.', flush=True)
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 2
        time.sleep(min(2, remaining))
