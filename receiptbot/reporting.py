"""Lokale Ableitungen ausschließlich aus verifizierten Originalen."""
from collections import defaultdict
import csv
import json
import os
from pathlib import Path
import tempfile
from .archive import file_digest
from .parsing import parse_text, read_pdf
from .workflow import Exports


def atomic_write(path, write, encoding="utf-8"):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, newline='', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def parse_all(data, output):
    store = Exports(data, output)
    rows = store.originals()
    for row in rows:
        source = Path(row['path'])
        if file_digest(source) != (row['byte_count'], row['sha256']):
            raise ValueError('Original fehlt oder Hash abweichend; Verarbeitung angehalten.')
        metadata = json.loads(row['metadata'])
        if metadata.get('original_format') in ('png','jpeg'):
            from .images import captured_app_text
            parsed = parse_text(captured_app_text(metadata), row['merchant'])
            for key in ('source_ui_text','source_ui_text_sha256','source_method','original_format','image_verification'):
                parsed[key] = metadata[key]
            if metadata['image_verification']['ui_text_coverage'] < 1:
                parsed['warnings'] = sorted(set(parsed['warnings'] + ['image_ocr_text_difference']))
        else:
            parsed = parse_text(read_pdf(source), row['merchant'])
            parsed.update(original_format='pdf', source_method='pdf_text')
        for key in ('list_total_cents','list_total_mismatch','ui_total_source'):
            if key in metadata:
                parsed[key] = metadata[key]
        if metadata.get('list_total_mismatch'):
            parsed['warnings'] = sorted(set(parsed['warnings'] + ['app_list_total_mismatch']))
        parsed.update(sha256=row['sha256'], source=str(source), status='review_required' if parsed['warnings'] else 'parsed')
        target = Path(output) / 'processed' / (row['merchant'] + '-' + row['sha256'] + '.json')
        atomic_write(target, lambda handle: json.dump(parsed, handle, ensure_ascii=False, indent=2))
    return len(rows)


def csv_cell(value):
    # Tabellenformeln in untrusted Artikeltexten verhindern. Kanonisches JSON bleibt unverändert.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def write_csv(path, fields, rows):
    def write(handle):
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_cell(value) for key, value in row.items()})
    atomic_write(path, write)


def report(data, output):
    # Immer aus aktuellem Hash-geprüften Bestand erzeugen, keine alten/externen JSON-Dateien einsammeln.
    parse_all(data, output)
    receipts, items, bookings = [], [], []
    groups = defaultdict(lambda: {'total_cents': 0, 'count': 0, 'review_count': 0})
    for original in Exports(data, output).originals():
        path = Path(output) / 'processed' / (original['merchant'] + '-' + original['sha256'] + '.json')
        parsed = json.loads(path.read_text())
        from .bookings import booking_rows
        bookings.extend(booking_rows(parsed))
        row = dict(parsed)
        row['warnings'] = ';'.join(parsed['warnings'])
        row['taxes'] = json.dumps(parsed['taxes'], ensure_ascii=False)
        receipts.append(row)
        for index, item in enumerate(parsed['items'], 1):
            items.append(dict(item, merchant=parsed['merchant'], sha256=parsed['sha256'], source=parsed['source'],
                              line_number=index, status=parsed['status']))
        if parsed['date'] and parsed['currency'] and parsed['total_cents'] is not None:
            group = groups[(parsed['date'][:7], parsed['merchant'], parsed['currency'])]
            group['total_cents'] += parsed['total_cents']
            group['count'] += 1
            group['review_count'] += bool(parsed['warnings'])
    destination = Path(output) / 'reports'
    write_csv(destination / 'receipts.csv', ['merchant', 'branch', 'register', 'receipt_id', 'date', 'time', 'currency', 'original_format', 'source_method',
        'total_cents', 'list_total_cents', 'taxes', 'source', 'sha256', 'status', 'warnings'], receipts)
    write_csv(destination / 'items.csv', ['merchant', 'sha256', 'source', 'line_number', 'description',
        'quantity', 'unit', 'unit_price_cents', 'amount_cents', 'tax_code', 'kind', 'raw_line', 'status'], items)
    write_csv(destination / 'monthly.csv', ['month', 'merchant', 'currency', 'total_cents', 'count', 'review_count'],
        [dict(month=key[0], merchant=key[1], currency=key[2], **value) for key, value in sorted(groups.items())])
    from .bookings import write_bookings
    write_bookings(destination / 'buchungen.csv', bookings)
    return len(receipts), len(items)
