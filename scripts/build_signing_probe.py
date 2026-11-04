"""Kleine Diagnose-App mit demselben Personal Team bauen, ohne private Build-Logs."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    os.umask(0o077)
    config = json.loads((ROOT / 'config.local.json').read_text())
    if not all(config.get(key) for key in ('team_id', 'wda_bundle_id', 'udid')):
        raise SystemExit('Lokale Signierungskonfiguration fehlt.')
    bundle = config.get('signing_probe_bundle_id') or config['wda_bundle_id'] + '.probe'
    config['signing_probe_bundle_id'] = bundle
    with (ROOT / 'config.local.json').open('w') as handle:
        handle.write(json.dumps(config, indent=2) + '\n')
    env = os.environ.copy()
    env.setdefault('DEVELOPER_DIR', '/Applications/Xcode.app/Contents/Developer')
    derived = ROOT / 'data/signing-probe/DerivedData'
    derived.mkdir(mode=0o700, parents=True, exist_ok=True)
    args = ['xcodebuild', '-project', str(ROOT / 'diagnostics/signing-probe/SigningProbe.xcodeproj'),
            '-target', 'SigningProbe', '-configuration', 'Debug', '-sdk', 'iphoneos',
            '-allowProvisioningUpdates', 'DEVELOPMENT_TEAM=' + config['team_id'],
            'RECEIPTBOT_PROBE_BUNDLE_ID=' + bundle,
            'SYMROOT=' + str(derived / 'Products'), 'OBJROOT=' + str(derived / 'Intermediates'), 'build']
    print('Baue lokale Diagnose-App; private Build-Ausgaben unterdrückt.', flush=True)
    try:
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        print('Build-Zeitlimit erreicht.')
        return 2
    print('Diagnose-Build Exit:', result.returncode)
    for phrase, category in [
        ('No profiles for', 'Provisioning-Profil fehlt'), ('requires a development team', 'Team fehlt'),
        ('BUILD SUCCEEDED', 'Build erfolgreich'), ('error:', 'Xcode-Fehler vorhanden'),
    ]:
        if phrase in result.stdout + result.stderr:
            print(category)
    if result.returncode:
        for line in (result.stdout + result.stderr).splitlines():
            if 'error:' not in line:
                continue
            for key in ('team_id', 'udid', 'wda_bundle_id', 'signing_probe_bundle_id'):
                if config.get(key):
                    line = line.replace(config[key], '[lokaler Wert]')
            line = re.sub(r'[\w.+-]+@[\w.-]+', '[E-Mail]', line)
            line = re.sub(r'/Users/[^/\s]+', '/Users/[lokal]', line)
            line = re.sub(r'Apple Development:.*', 'Apple Development: [lokal]', line)
            print(line[:800])
    return 0 if result.returncode == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
