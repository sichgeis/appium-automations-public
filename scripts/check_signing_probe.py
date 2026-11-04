"""Nur die lokale Diagnose-App installieren/starten, keine Händlerdaten lesen."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from receiptbot.session import device_lock


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='Installierte Diagnose-App starten; Installation nur auf ausdrücklichen Wunsch.')
    parser.add_argument('--install', action='store_true', help='Diagnose-App vor dem Start installieren')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config.local.json').read_text())
    app = ROOT / 'data/signing-probe/DerivedData/Products/Debug-iphoneos/SigningProbe.app'
    if not config.get('signing_probe_bundle_id') or (args.install and not app.is_dir()):
        raise SystemExit('Diagnose-Konfiguration oder gewünschter Installationsbuild fehlt.')
    env = os.environ.copy()
    env.setdefault('DEVELOPER_DIR', '/Applications/Xcode.app/Contents/Developer')
    steps = []
    if args.install:
        steps.append(('installation', ['device', 'install', 'app', '--device', config['udid'], str(app)]))
    steps.append(('launch', ['device', 'process', 'launch', '--device', config['udid'], config['signing_probe_bundle_id']]))
    report = {}
    with device_lock():
        for name, args in steps:
            print('Diagnose-App: ' + name, flush=True)
            try:
                result = subprocess.run(['xcrun', 'devicectl', *args, '--json-output', '-', '--timeout', '25'],
                                        env=env, capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                report[name] = {'timeout': True}
                break
            raw = (result.stdout + result.stderr).lower()
            report[name] = {
                'exit': result.returncode,
                'developer_certificate_not_trusted': 'developer app certificate is not trusted' in raw,
                'profile_not_explicitly_trusted': 'not been explicitly trusted' in raw or 'not explicitly trusted' in raw,
                'identity_invalid': 'identity used to sign the executable is no longer valid' in raw,
                'device_locked': 'device is locked' in raw or 'device was not unlocked' in raw,
            }
            print(json.dumps({name: report[name]}), flush=True)
            if result.returncode:
                break
    directory = ROOT / 'data/signing-probe/results'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = directory / (uuid4().hex + '.json')
    with destination.open('x') as handle:
        handle.write(json.dumps(report, indent=2) + '\n')
    if report.get('launch', {}).get('exit') == 0:
        print('Gewöhnliche selbst signierte Test-App auf dem echten iPhone gestartet.')
        return 0
    print('Diagnose-App konnte nicht starten. Keine Rohdaten gespeichert oder ausgegeben.')
    return 2


if __name__ == '__main__':
    sys.exit(main())
