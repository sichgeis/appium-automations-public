"""Nur das lokale iOS-WDA-Runner-Target für Personal-Team-Signierung vorbereiten."""
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent.parent


def main():
    os.umask(0o077)
    config_path = ROOT / 'config.local.json'
    config = json.loads(config_path.read_text())
    project = ROOT / 'node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj/project.pbxproj'
    original = project.read_text()
    converted = subprocess.run(['plutil', '-convert', 'json', '-o', '-', str(project)],
                               capture_output=True, text=True, check=True)
    objects = json.loads(converted.stdout)['objects']
    targets = [v for v in objects.values() if v.get('isa') == 'PBXNativeTarget'
               and v.get('name') == 'WebDriverAgentRunner']
    if len(targets) != 1:
        raise ValueError('WDA-iOS-Runner nicht eindeutig gefunden; keine Änderung.')
    bundle = config.get('wda_bundle_id') or 'io.receiptbot.wda.' + uuid.uuid4().hex
    if not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', bundle):
        raise ValueError('Ungültige lokale WDA-Bundle-ID; keine Änderung.')
    configurations = objects[targets[0]['buildConfigurationList']]['buildConfigurations']
    updated = original
    for identifier in configurations:
        pattern = rf'(^\t\t{re.escape(identifier)} /\* .*? \*/ = \{{\n)(.*?)(^\t\t\}};)'
        match = re.search(pattern, updated, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError('Unbekanntes WDA-Projektformat; keine Änderung.')
        block = match.group(2)
        block, count = re.subn(r'PRODUCT_BUNDLE_IDENTIFIER = [^;]+;',
                              f'PRODUCT_BUNDLE_IDENTIFIER = {bundle};', block)
        if count != 1:
            raise ValueError('WDA-Bundle-Feld nicht eindeutig; keine Änderung.')
        if re.search(r'CODE_SIGN_STYLE = [^;]+;', block):
            block = re.sub(r'CODE_SIGN_STYLE = [^;]+;', 'CODE_SIGN_STYLE = Automatic;', block)
        else:
            block = block.replace('buildSettings = {', 'buildSettings = {\n\t\t\t\tCODE_SIGN_STYLE = Automatic;', 1)
        updated = updated[:match.start(2)] + block + updated[match.end(2):]
    backup = ROOT / 'data/wda/project.pbxproj.before-setup'
    backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not backup.exists():
        with backup.open('x') as handle:
            handle.write(original)
    config['wda_bundle_id'] = bundle
    # Keine Team-Auswahl und keine Anmeldung automatisieren.
    with config_path.open('w') as handle:
        handle.write(json.dumps(config, indent=2) + '\n')
    os.chmod(config_path, 0o600)
    project.write_text(updated)
    print('WDA-iOS-Runner: eindeutige lokale Bundle-ID und automatische Signierung vorbereitet.')
    print('Personal Team muss noch direkt in Xcode ausgewählt werden. Kein Build/Install gestartet.')


if __name__ == '__main__':
    main()
