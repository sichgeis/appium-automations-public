"""Gezielte installierte Händler-Metadaten, niemals UI/Belege oder komplette App-Liste speichern."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4
from .retailers import RETAILERS, app_candidates
from .readiness import device_status
from .session import ROOT, device_lock, load_config, select_local_xcode


def apply_candidate(config, merchant, candidates):
    if len(candidates) != 1:
        raise ValueError('Keine eindeutige App-Zuordnung; vorhandene Konfiguration unverändert lassen.')
    candidate = candidates[0]
    old = config.get('apps', {}).get(merchant, {})
    if old.get('bundle_id') and old['bundle_id'] != candidate['bundle_id']:
        raise ValueError('Andere Bundle-ID bereits konfiguriert; erst tatsächliche Bon-App prüfen. Nichts überschrieben.')
    config.setdefault('apps', {})[merchant] = dict(old, bundle_id=candidate['bundle_id'],
        status='Installationsmetadaten erkannt; Bonnavigation/Export nicht verifiziert')


def discover_apps(merchant, apply=False):
    if merchant not in RETAILERS:
        raise ValueError('Unbekannter Händler.')
    config = load_config()
    if not config.get('udid'):
        raise ValueError('Konfiguriertes echtes iPhone fehlt; keine automatische Gerätewahl.')
    select_local_xcode()
    with device_lock():
        passed, reason = device_status(config)
        if not passed:
            raise ValueError(reason)
        try:
            result = subprocess.run(['xcrun', 'devicectl', 'device', 'info', 'apps', '--include-all-apps', '--device', config['udid'],
                '--json-output', '-', '--timeout', '15'], capture_output=True, text=True, timeout=18)
        except subprocess.TimeoutExpired:
            raise ValueError('App-Metadatenabfrage abgelaufen; keine Konfiguration geändert.') from None
        if result.returncode:
            raise ValueError('Installierte Apps nicht lesbar; keine Rohdaten ausgegeben oder Konfiguration geändert.')
        candidates = app_candidates(json.loads(result.stdout), merchant)
        directory = ROOT / 'data/app-discovery'
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (directory / (merchant + '-' + uuid4().hex + '.json')).open('x', encoding='utf-8') as handle:
            os.chmod(handle.name, 0o600)
            json.dump({'merchant': merchant, 'candidates': candidates, 'ui_inspected': False}, handle, ensure_ascii=False)
        if apply:
            apply_candidate(config, merchant, candidates)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False, encoding='utf-8') as handle:
                    temporary = Path(handle.name)
                    json.dump(config, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, ROOT / 'config.local.json')
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        print('Gezielte App-Kandidaten: ' + str(len(candidates)) + '. Nur passende Metadaten lokal unter data/app-discovery gespeichert.')
        print('Bundle-ID lokal übernommen; Adapter/Parser/Export bleiben ungeprüft.' if apply else
              'Keine Konfiguration geändert. Kein Treffer beweist nicht, dass die App fehlt; mehrere Treffer erfordern eine gezielte Prüfung.')
    return 0
