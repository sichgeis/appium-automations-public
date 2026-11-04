"""Lokaler Bildleser/OCR; rohe Texte ausschließlich als interne Daten zurückgeben."""
import json
import os
from pathlib import Path
import subprocess
from .session import ROOT, select_local_xcode


def read_image(path):
    select_local_xcode()
    source = ROOT / 'scripts/read_receipt_image.swift'
    directory = ROOT / 'data/bin'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    binary = directory / 'read-receipt-image'
    if not binary.exists() or binary.stat().st_mtime_ns < source.stat().st_mtime_ns:
        cache = ROOT / 'data/swift-module-cache'
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            build = subprocess.run(['xcrun', 'swiftc', '-module-cache-path', str(cache), str(source), '-o', str(binary)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except subprocess.TimeoutExpired:
            raise ValueError('Lokaler Bildleser-Build abgelaufen; kein Original verifiziert.') from None
        if build.returncode:
            raise ValueError('Lokaler ImageIO-/Vision-Leser nicht baubar; Xcode prüfen.')
        os.chmod(binary, 0o700)
    try:
        result = subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise ValueError('Lokale Bilderkennung abgelaufen; Eingang bleibt ungeprüft.') from None
    if result.returncode:
        raise ValueError('Bild nicht vollständig lesbar oder ohne brauchbare lokale Texterkennung.')
    data = json.loads(result.stdout)
    if (data.get('complete') is not True or data.get('format') not in ('public.png', 'public.jpeg')
            or not isinstance(data.get('observations'), list) or not data['observations']):
        raise ValueError('Unerwartetes Ergebnis des lokalen Bildlesers.')
    rows = []
    for item in sorted(data['observations'], key=lambda item: -(item['y'] + item['height']/2)):
        middle = item['y'] + item['height']/2
        row = next((row for row in rows if abs(row['middle']-middle) <= .4*max(row['height'],item['height'])), None)
        if row is None:
            row = {'middle': middle, 'height': item['height'], 'items': []}
            rows.append(row)
        row['items'].append(item)
    data['text'] = '\n'.join(' '.join(item['text'] for item in sorted(row['items'],key=lambda item:item['x']))
                             for row in sorted(rows,key=lambda row:-row['middle']))
    return data


def monetary_tokens(text):
    from collections import Counter
    from decimal import Decimal
    import re
    text = text.translate(str.maketrans({'−':'-', '–':'-', '—':'-'}))
    # OCR kann zusammengehörige Dezimalstellen als getrennte Textfragmente liefern.
    text = re.sub(r'(?<=\d)([,.])\s+(?=\d{2}(?!\d))', r'\1', text)
    tokens = []
    for value in re.findall(r'(?<![\d.,])(-?\s*\d+(?:\.\d{3})*,\d{2}|-?\s*\d+\.\d{2})(?![\d.])', text):
        value = re.sub(r'\s', '', value)
        if ',' in value:
            value = value.replace('.', '').replace(',', '.')
        tokens.append(int(Decimal(value) * 100))
    return Counter(tokens)


def date_tokens(text):
    from collections import Counter
    from datetime import datetime
    import re
    values = []
    for value in re.findall(r'\b(?:\d{2}\.\d{2}\.\d{4}|\d{2}\.\d{2}\.\d{2})\b', text):
        try:
            values.append(datetime.strptime(value, '%d.%m.%Y' if len(value)==10 else '%d.%m.%y').date().isoformat())
        except ValueError:
            pass
    return Counter(values)


def validate_image_receipt(path, expected):
    from difflib import SequenceMatcher
    import hashlib
    import re
    from .parsing import parse_text
    if expected['merchant'] != 'lidl':
        raise ValueError('Bild-Originalformat für diesen Händler noch nicht am Gerät verifiziert.')
    image = read_image(path)
    app_text, recognized = expected['text'], image['text']
    parsed = parse_text(app_text, expected['merchant'])
    if (parsed['date'] != expected['date'] or parsed['total_cents'] != expected['total_cents']
            or parsed['currency'] != 'EUR'):
        raise ValueError('App-Text passt nicht eindeutig zum ausgewählten Bildbeleg.')
    expected_chars = ''.join(c for c in app_text.casefold() if c.isalnum())
    image_chars = ''.join(c for c in recognized.casefold() if c.isalnum())
    if len(expected_chars) < 80:
        raise ValueError('Zu wenig belegter App-Text für sichere Bildzuordnung.')
    matches = SequenceMatcher(None, expected_chars, image_chars, autojunk=False).get_matching_blocks()
    coverage = sum(match.size for match in matches) / len(expected_chars)
    missing_money = monetary_tokens(app_text) - monetary_tokens(recognized)
    recognized_fields = parse_text(recognized, expected['merchant'])
    fiscal_keys = ('tse_serial','tse_transaction','register')
    fiscal_exact = all(parsed.get(key) and parsed.get(key)==recognized_fields.get(key) for key in fiscal_keys)
    fiscal_conflict = any(parsed.get(key) and recognized_fields.get(key) and parsed[key]!=recognized_fields[key] for key in fiscal_keys)
    missing_dates = date_tokens(app_text) - date_tokens(recognized)
    failed = []
    if coverage < .99 and not (fiscal_exact and coverage >= .95):
        failed.append('App-Textabgleich')
    if missing_money:
        failed.append('Geldwerte')
    if missing_dates:
        failed.append('Datumswerte')
    if fiscal_conflict:
        failed.append('widersprüchliche TSE-/Kassenkennung')
    if not re.search(r'\blidl\b', recognized, re.I):
        failed.append('Händler')
    if failed:
        raise ValueError('Bildzuordnung ungeklärt: ' + ', '.join(failed) + '. Eingang bleibt unverifiziert.')
    if coverage < 1:
        parsed['warnings'] = sorted(set(parsed['warnings'] + ['image_ocr_text_difference']))
    parsed.update(original_format='png' if image['format'] == 'public.png' else 'jpeg',
        source_method='app_accessibility', source_ui_text=app_text,
        source_ui_text_sha256=hashlib.sha256(app_text.encode()).hexdigest(),
        image_verification=dict(complete=image['complete'], width=image['width'], height=image['height'],
                                ui_text_coverage=coverage, all_money_values_matched=True,
                                fiscal_identity_matched=fiscal_exact,
                                verification_mode='fiscal_identity_and_text' if coverage < .99 else 'strict_text_and_money',
                                method='local_vision_tiled_ocr_and_app_text'))
    return parsed


def captured_app_text(metadata):
    import hashlib
    text = metadata.get('source_ui_text')
    if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != metadata.get('source_ui_text_sha256'):
        raise ValueError('Kein unveränderter, dem Bildoriginal zugeordneter App-Text vorhanden.')
    return text
