"""Begrenzte/persistente lokale Appium-Prüfung ohne rohe Startprotokolle."""
import argparse
from collections import deque
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from receiptbot.session import load_config, select_local_xcode, session


def scrub(text, private):
    for value in sorted(filter(None, private), key=len, reverse=True):
        text = text.replace(value, '[lokaler Wert]')
    text = re.sub(r'[\w.+-]+@[\w.-]+', '[E-Mail]', text)
    text = re.sub(r'/Users/[^/\s]+', '/Users/[lokal]', text)
    text = re.sub(r'\b[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{8,}\b', '[Kennung]', text)
    text = re.sub(r'\b[A-Z0-9]{10}\b', '[Signierung]', text)
    return text


@contextmanager
def server(logs):
    with socket.socket() as check:
        if check.connect_ex(('127.0.0.1', 4723)) == 0:
            raise ValueError('Appium-Port belegt; vorhandenen Prozess nicht verändert.')
    process = subprocess.Popen(['sh', str(ROOT / 'scripts/appium.sh'), '--address', '127.0.0.1',
        '--port', '4723', '--log-level', 'warn', '--log-no-colors'], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    def consume():
        for line in process.stdout:
            # Nur Startdiagnosen im RAM behalten; kein Logfile.
            if any(word in line.lower() for word in ('wda', 'xcode', 'error', 'automation', 'testmanager')):
                logs.append(line.rstrip())
    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise ValueError('Eigener Appium-Server konnte nicht starten.')
            try:
                with urllib.request.urlopen('http://127.0.0.1:4723/status', timeout=1) as response:
                    if json.load(response)['value']['ready']:
                        break
            except (OSError, ValueError):
                time.sleep(0.25)
        else:
            raise ValueError('Lokaler Appium-Server antwortet nicht rechtzeitig.')
        yield
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        reader.join(timeout=2)


def save_source(driver, app):
    directory = ROOT / 'data/debug'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f'{app}-{uuid4().hex}.xml'
    with path.open('x') as handle:
        handle.write(driver.page_source)
    return str(path)


def interact(driver, app):
    from appium.webdriver.common.appiumby import AppiumBy
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    strategies = {'accessibility id': AppiumBy.ACCESSIBILITY_ID,
                  'predicate': AppiumBy.IOS_PREDICATE, 'class chain': AppiumBy.IOS_CLASS_CHAIN}
    for line in sys.stdin:
        command = json.loads(line)
        action = command.get('action')
        if action == 'quit':
            return
        if driver.is_locked():
            raise ValueError('iPhone ist gesperrt; Bedienung angehalten. Bitte selbst entsperren, keine Klickwiederholung.')
        if action == 'source':
            result = {'source_path': save_source(driver, app)}
        elif action == 'tap':
            locator = (strategies[command['using']], command['value'])
            element = WebDriverWait(driver, 12).until(EC.element_to_be_clickable(locator))
            element.click()
            result = {'tapped': True}
        elif action == 'screenshot':
            directory = ROOT / 'data/debug'
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = directory / f'{app}-{uuid4().hex}.png'
            with path.open('xb') as handle:
                handle.write(driver.get_screenshot_as_png())
            result = {'screenshot_path': str(path)}
        else:
            raise ValueError('Unbekannter Bedienbefehl; Sitzung wird angehalten.')
        print(json.dumps(result), flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='Echte lokale Appium-Session ohne App-Reset prüfen.')
    parser.add_argument('--app', choices=('kaufland', 'dm', 'lidl', 'rossmann'), default='kaufland')
    parser.add_argument('--save-ui', action='store_true', help='UI-Dump nur lokal speichern')
    parser.add_argument('--interactive', action='store_true', help='Einzelbefehle per JSON-Zeilen; keine automatischen Klicks')
    args = parser.parse_args()
    select_local_xcode()
    config = load_config()
    if args.interactive:
        config['new_command_timeout'] = 300
    private = [config.get(k, '') for k in ('udid', 'team_id', 'wda_bundle_id', 'signing_probe_bundle_id')]
    # Gerätenamen nur für die lokale Redigierung ermitteln.
    details = subprocess.run(['xcrun', 'devicectl', 'device', 'info', 'details', '--device', config['udid'],
        '--json-output', '-', '--timeout', '10'], capture_output=True, text=True, timeout=15)
    if details.returncode == 0:
        private.append(json.loads(details.stdout).get('result', {}).get('deviceProperties', {}).get('name', ''))
    logs = deque(maxlen=30)
    try:
        with server(logs), session(config, args.app) as driver:
            print(json.dumps({'session_ready': True, 'app': args.app, 'no_reset': True}), flush=True)
            if args.save_ui:
                print(json.dumps({'source_path': save_source(driver, args.app)}), flush=True)
            if args.interactive:
                try:
                    interact(driver, args.app)
                except Exception:
                    try:
                        print(json.dumps({'failure_source_path': save_source(driver, args.app)}), flush=True)
                    except Exception:
                        pass
                    raise
        return 0
    except KeyboardInterrupt:
        print('Sitzung abgebrochen und eigener Server beendet.', flush=True)
        return 130
    except Exception as exc:
        print('Session-/Bedienfehler:', type(exc).__name__, scrub(getattr(exc, 'msg', str(exc)), private)[:2400], flush=True)
        for line in list(logs)[-12:]:
            print('Redigierte Startdiagnose:', scrub(line, private)[:900], flush=True)
        return 2


if __name__ == '__main__':
    sys.exit(main())
