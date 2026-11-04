"""WDA lokal bauen; private Xcode-Ausgaben bleiben im Arbeitsspeicher."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    os.umask(0o077)
    config = json.loads((ROOT / 'config.local.json').read_text())
    if not all(config.get(k) for k in ('udid', 'team_id', 'wda_bundle_id')):
        raise SystemExit('Lokale WDA-Signierungskonfiguration unvollständig.')
    env = os.environ.copy()
    env.setdefault('DEVELOPER_DIR', '/Applications/Xcode.app/Contents/Developer')
    derived = ROOT / 'data/wda/DerivedData'
    derived.mkdir(parents=True, exist_ok=True, mode=0o700)
    args = ['xcodebuild', '-project', str(ROOT / 'node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj'),
            '-scheme', 'WebDriverAgentRunner', '-configuration', 'Debug',
            '-destination', 'id=' + config['udid'], '-destination-timeout', '30',
            '-derivedDataPath', str(derived), '-allowProvisioningUpdates',
            'build-for-testing']
    print('WDA-Build gestartet; private Xcode-Ausgaben werden nicht gespeichert oder ausgegeben.', flush=True)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        output, _ = process.communicate(timeout=300)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        print('WDA-Build abgebrochen; keine Rohlogs gespeichert.')
        return 2
    print('WDA-Build Exit:', process.returncode)
    for text, label in [
        ('BUILD SUCCEEDED', 'Build erfolgreich'),
        ('TEST BUILD SUCCEEDED', 'Test-Build erfolgreich'),
        ('requires a development team', 'Development Team fehlt'),
        ('No profiles for', 'Passendes Provisioning-Profil fehlt'),
        ('Signing certificate', 'Signierungszertifikat wird in einer Diagnose erwähnt'),
        ('Developer Mode is disabled', 'Entwicklermodus deaktiviert'),
        ('device is locked', 'iPhone ist gesperrt'),
        ('Preparing', 'Xcode hat Gerätevorbereitung ausgeführt'),
        ('error:', 'Mindestens eine Xcode-Fehlermeldung; Rohinhalt unterdrückt'),
    ]:
        if text in output:
            print(label)
    print('Build-/Provisioning-Artefakte liegen ausschließlich lokal unter data/wda/DerivedData.')
    return 0 if process.returncode == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
