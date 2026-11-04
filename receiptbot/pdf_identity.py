"""Gleicher belegter Bon trotz neuer PDF-Metadaten; Originalbytes niemals ändern."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile


def receipt_identity(parsed):
    import json
    keys = ('branch', 'register', 'date', 'receipt_id')
    if not all(parsed.get(key) for key in keys):
        if all(parsed.get(key) for key in ('date','tse_serial','tse_transaction')):
            return json.dumps(['tse', parsed['date'], parsed['tse_serial'], parsed['tse_transaction']])
        if all(parsed.get(key) for key in ('date','fiscal_signature','signature_counter')):
            return json.dumps(['fiscal_signature', parsed['date'], parsed['fiscal_signature'], parsed['signature_counter']])
        return None
    return json.dumps([parsed[key] for key in keys])


def visual_fingerprint(path):
    with Path(path).open('rb') as handle:
        signature = handle.read(8)
    if signature.startswith(b'\x89PNG\r\n\x1a\n') or signature.startswith(b'\xff\xd8'):
        from .images import read_image
        data = read_image(path)
        return ('image', data['width'], data['height'], tuple(data['pixel_layout']), data['pixel_sha256'])
    executable = shutil.which('pdftoppm')
    if not executable:
        raise ValueError('Gleiche Bon-ID mit anderen PDF-Bytes: visueller Vergleich benötigt lokales pdftoppm; zur Prüfung angehalten.')
    with tempfile.TemporaryDirectory(prefix='receiptbot-pdf-compare-') as directory:
        try:
            result = subprocess.run([executable, '-r', '72', '-png', str(path), str(Path(directory) / 'page')],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except subprocess.TimeoutExpired:
            raise ValueError('PDF-Vergleich abgelaufen; keine Inhaltsdublette bestätigt.') from None
        pages = sorted(Path(directory).glob('page-*.png'))
        if result.returncode or not pages:
            raise ValueError('PDF-Vergleich fehlgeschlagen; keine Inhaltsdublette bestätigt.')
        return tuple(hashlib.sha256(page.read_bytes()).hexdigest() for page in pages)
