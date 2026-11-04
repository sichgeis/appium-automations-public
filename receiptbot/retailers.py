"""Händlerstatus und sichere Freigabe; keine erfundenen App-Kennungen/Selektoren."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Retailer:
    name: str
    name_pattern: str
    adapter_implemented: bool = False
    parser_implemented: bool = False
    device_export_verified: bool = False
    full_history_implemented: bool = False


RETAILERS = {
    'kaufland': Retailer('Kaufland', r'\bkaufland\b', True, True, True, True),
    'dm': Retailer('dm', r'\bdm\b', True, True, True),
    'lidl': Retailer('Lidl / Lidl Plus', r'\blidl\b', True, True, True),
    'rossmann': Retailer('Rossmann', r'\brossmann\b', True, True, True),
}


def require_export_implementation(merchant):
    spec = RETAILERS.get(merchant)
    if spec is None:
        raise ValueError('Unbekannter Händler.')
    if not spec.adapter_implemented or not spec.parser_implemented:
        raise ValueError(spec.name + ': Adapter/Parser noch nicht implementiert und nicht am Gerät verifiziert. Keine Navigation ausgeführt.')


def app_candidates(payload, merchant):
    """App-Namen sind nur Suchhinweise, niemals Beweis für digitale Bons."""
    spec = RETAILERS.get(merchant)
    if spec is None:
        raise ValueError('Unbekannter Händler.')
    result = payload.get('result') if isinstance(payload, dict) else None
    apps = result.get('apps') if isinstance(result, dict) else None
    if not isinstance(apps, list):
        raise ValueError('Unbekanntes App-Metadatenformat; keine Kennung übernommen.')
    candidates = {}
    for app in apps:
        if not isinstance(app, dict):
            raise ValueError('Unbekanntes App-Metadatenformat; keine Kennung übernommen.')
        name, bundle = app.get('name'), app.get('bundleIdentifier')
        if not isinstance(name, str) or not re.search(spec.name_pattern, name, re.IGNORECASE):
            continue
        if not isinstance(bundle, str) or not bundle.strip():
            raise ValueError('Gefundene Händler-App ohne lesbare Bundle-ID; keine Kennung übernommen.')
        candidate = {'name': name, 'bundle_id': bundle,
                     'version': app.get('version') if isinstance(app.get('version'), str) else None}
        if bundle in candidates and candidates[bundle] != candidate:
            raise ValueError('Widersprüchliche Metadaten zur selben App; keine Kennung übernommen.')
        candidates[bundle] = candidate
    return list(candidates.values())
