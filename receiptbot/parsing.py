"""Konservativer lokaler Parser. Fehlende/mehrdeutige Werte bleiben leer."""
from datetime import datetime
from decimal import Decimal
import logging
from pathlib import Path
import re
import warnings

MONEY = r'-?\d+(?:\.\d{3})*,\d{2}'


def cents(value):
    return int(Decimal(value.replace('.', '').replace(',', '.')) * 100)


def normalized(text):
    return re.sub(r'\s+', '', text).casefold()


def read_pdf(path):
    from pypdf import PdfReader
    path = Path(path)
    with path.open('rb') as stream:
        if stream.read(5) != b'%PDF-':
            raise ValueError('Originalformat ist kein PDF. Datei bleibt im Eingang; anderes Format muss zuerst geprüft werden.')
        stream.seek(max(0, path.stat().st_size - 2048))
        if not stream.read().rstrip().endswith(b'%%EOF'):
            raise ValueError('PDF-Endmarkierung fehlt; Übertragung oder Format unvollständig.')
    # Fremde PDF-Inhalte niemals über Parserwarnungen in Logs ausgeben.
    before = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
                raise ValueError('PDF verschlüsselt oder unerwartete Seitenzahl; manuelle Prüfung nötig.')
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception:
        raise ValueError('PDF lässt sich nicht vollständig lesen; Eingang bleibt ausstehend.') from None
    finally:
        logging.disable(before)
    if len(text.strip()) < 30:
        raise ValueError('PDF ohne brauchbare Textebene: lokale OCR/visuelle Prüfung muss separat eingerichtet werden.')
    return text


def parse_text(text, merchant):
    if merchant == 'rossmann':
        from .parsers.rossmann import parse_rossmann
        return parse_rossmann(text)
    if merchant == 'dm':
        from .parsers.dm import parse_dm
        return parse_dm(text)
    if merchant == 'lidl':
        from .parsers.lidl import parse_lidl
        return parse_lidl(text)
    result = {'merchant': merchant, 'receipt_id': None, 'date': None, 'time': None,
              'currency': None, 'total_cents': None, 'branch': None, 'register': None, 'taxes': [],
              'items': [], 'warnings': [], 'unparsed_lines': [], 'parser_version': 1}
    if merchant != 'kaufland':
        result['warnings'].append('merchant_parser_not_implemented')
        return result
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not any('kaufland' in line.casefold() for line in lines):
        result['warnings'].append('merchant_not_found')
        return result
    # Keine Terminal-, Karten- oder Transaktionsnummer als vermeintliche Bon-ID übernehmen.
    totals = {cents(m.group(1)) for line in lines
              if (m := re.fullmatch(r'(?:Summe|SUMME)\s+(' + MONEY + r')(?:\s+EUR)?', line))}
    if len(totals) == 1:
        result['total_cents'] = totals.pop()
    else:
        result['warnings'].append('total_missing_or_ambiguous')
    if re.search(r'\bEUR\b|€', text):
        result['currency'] = 'EUR'
    dates = set()
    for match in re.finditer(r'\b(\d{2}\.\d{2}\.\d{4}|\d{2}\.\d{2}\.\d{2})\b', text):
        try:
            value = match.group(1)
            dates.add(datetime.strptime(value, '%d.%m.%Y' if len(value) == 10 else '%d.%m.%y').date().isoformat())
        except ValueError:
            pass
    if len(dates) == 1:
        result['date'] = dates.pop()
    else:
        result['warnings'].append('date_missing_or_ambiguous')
    times = set(re.findall(r'\b(\d{2}:\d{2})\s+Uhr\b', text))
    if len(times) == 1:
        result['time'] = times.pop()
    # Erst am echten Original-PDF nachgewiesener Bonfooter. Karten-BNr/TA-Nr bleiben außen vor.
    footers = [match for line in lines if (match := re.fullmatch(
        r'Datum:\s*(\d{2}\.\d{2}\.\d{2})\s+Zeit:\s*(\d{2}:\d{2}:\d{2})\s+Bon:\s*(\d+)', line))]
    branches = [match for line in lines if (match := re.fullmatch(r'Filiale:\s*(\d+)\s+Kasse:\s*(\d+)', line))]
    if len(footers) == 1:
        footer = footers[0]
        if result['date'] == datetime.strptime(footer[1], '%d.%m.%y').date().isoformat():
            result['time'], result['receipt_id'] = footer[2], footer[3]
    if len(branches) == 1:
        result['branch'], result['register'] = branches[0][1], branches[0][2]
    for line in lines:
        tax = re.fullmatch(r'([A-Z])\s+(\d+,\d{2})%\s+(' + MONEY + r')\s+(' + MONEY + r')\s+(' + MONEY + r')', line)
        if tax:
            result['taxes'].append({'code': tax[1], 'rate': tax[2].replace(',', '.'),
                'gross_cents': cents(tax[3]), 'net_cents': cents(tax[4]), 'tax_cents': cents(tax[5])})
    # Nur der beobachtete Kaufland-Artikelblock; Zahlungs-/Steuerzeilen bleiben draußen.
    start = next((i + 1 for i, line in enumerate(lines) if re.fullmatch(r'Preis\s+EUR', line)), None)
    end = next((i for i, line in enumerate(lines) if re.fullmatch(r'(?:Summe|SUMME)\s+' + MONEY + r'(?:\s+EUR)?', line)), None)
    if start is not None and end is not None and end >= start:
        pending = None
        for line in lines[start:end]:
            match = re.fullmatch(r'(.+?)\s+(' + MONEY + r')(?:\s+([A-Z]))?', line)
            if not match:
                if pending:
                    result['warnings'].append('unparsed_item_line')
                    result['unparsed_lines'].append(pending)
                pending = line
                continue
            description, value, tax = match.groups()
            quantity = unit = unit_price = None
            multiple = re.fullmatch(r'(.+?)\s+(\d+)\s*\*\s*(' + MONEY + r')', description)
            weight = re.fullmatch(r'(?:(.+?)\s+)?(\d+,\d{1,3})\s+(kg|g|l|ml)', description)
            if multiple:
                description, quantity, price = multiple.groups()
                unit, unit_price = 'piece', cents(price)
            elif weight:
                name, amount, unit = weight.groups()
                description = name or pending
                quantity = amount.replace(',', '.')
                pending = None
            elif pending:
                result['warnings'].append('unparsed_item_line')
                result['unparsed_lines'].append(pending)
                pending = None
            if not description:
                result['warnings'].append('unparsed_item_line')
                result['unparsed_lines'].append(line)
                continue
            kind = 'discount' if 'rabatt' in description.casefold() else 'deposit' if 'pfand' in description.casefold() else 'item'
            result['items'].append({'description': description, 'quantity': quantity, 'unit': unit,
                'unit_price_cents': unit_price, 'amount_cents': cents(value), 'tax_code': tax,
                'kind': kind, 'raw_line': line})
        if pending:
            result['warnings'].append('unparsed_item_line')
            result['unparsed_lines'].append(pending)
        if result['total_cents'] is not None and sum(i['amount_cents'] for i in result['items']) != result['total_cents']:
            result['warnings'].append('item_sum_mismatch')
    else:
        result['warnings'].append('item_layout_not_recognized')
    for tax in result['taxes']:
        if tax['gross_cents'] != tax['net_cents'] + tax['tax_cents']:
            result['warnings'].append('tax_sum_mismatch')
    if result['taxes'] and result['total_cents'] is not None and sum(t['gross_cents'] for t in result['taxes']) != result['total_cents']:
        result['warnings'].append('tax_total_mismatch')
    result['warnings'] = sorted(set(result['warnings']))
    return result


def validate_receipt(path, expected):
    with Path(path).open('rb') as handle:
        signature = handle.read(8)
    if signature.startswith(b'\x89PNG\r\n\x1a\n') or signature.startswith(b'\xff\xd8'):
        from .images import validate_image_receipt
        return validate_image_receipt(path, expected)
    text = read_pdf(path)
    parsed = parse_text(text, expected['merchant'])
    if (parsed['date'] != expected['date'] or parsed['total_cents'] != expected['total_cents']
            or parsed['currency'] != 'EUR' or 'merchant_not_found' in parsed['warnings']):
        raise ValueError('Eingang passt nicht eindeutig zu Händler, Datum und Summe des geöffneten Bons.')
    # Quick Look liefert getrennte PDF-Textabschnitte, keine fortlaufende Lesereihenfolge.
    if expected['merchant'] == 'rossmann':
        from .parsers.rossmann import fiscal_identity
        parts = expected.get('receipt_segments')
        if (not isinstance(parts,list) or not parts or any(not isinstance(p,str) for p in parts)
                or expected['text'] != '\n'.join(parts) or sum(map(len,parts)) < 80
                or any(normalized(part) not in normalized(text) for part in parts)):
            raise ValueError('Rossmann-PDF stimmt nicht mit allen beobachteten Bonzeilen überein.')
        observed = fiscal_identity(expected['text'])
        if not all(parsed.get(key) and parsed[key] == observed.get(key)
                   for key in ('fiscal_signature','signature_counter')):
            raise ValueError('Rossmann-PDF und App haben keine exakt gleiche belegte Fiskalsignatur.')
    elif expected['merchant'] == 'dm':
        from .parsers.dm import quicklook_segments_match,quicklook_total
        parts = expected.get('quicklook_segments')
        if (not isinstance(parts,list) or not parts or any(not isinstance(p,str) for p in parts)
                or expected['text'] != '\n'.join(parts) or sum(map(len,parts)) < 80
                or not quicklook_segments_match(parts,text)):
            raise ValueError('dm-PDF stimmt nicht mit allen beobachteten Quick-Look-Textabschnitten überein.')
        observed = parse_text(expected['text'],'dm')
        if not all(parsed.get(key) and parsed[key] == observed.get(key)
                   for key in ('register','tse_serial','tse_transaction')):
            raise ValueError('dm-PDF und Quick Look haben keine exakt gleiche belegte fiskalische Identität.')
        if expected.get('ui_total_source') and quicklook_total(parts) != parsed['total_cents']:
            raise ValueError('Gedruckte dm-SUMME in Vorschau und Original-PDF weichen ab.')
        if 'list_total_cents' in expected:
            parsed['list_total_cents'] = expected['list_total_cents']
        if expected.get('list_total_mismatch'):
            if (expected.get('ui_total_source') != 'quicklook_summe_confirmed_twice'
                    or expected.get('list_total_cents') == parsed['total_cents']):
                raise ValueError('Abweichender dm-Listenbetrag nicht durch erneute Auswahl bestätigt.')
            parsed.update(list_total_mismatch=True,ui_total_source=expected['ui_total_source'])
            parsed['warnings'] = sorted(set(parsed['warnings'] + ['app_list_total_mismatch']))
    else:
        observed = normalized(expected['text'])
        received = normalized(text)
        if len(observed) < 80 or observed not in received:
            raise ValueError('Original-PDF und sichtbarer vollständiger Bontext stimmen nicht eindeutig überein. Eingang zur Prüfung behalten.')
    parsed.update(original_format='pdf', source_method='pdf_text')
    return parsed
