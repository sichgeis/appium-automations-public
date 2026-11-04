"""Bytegetreue lokale Ablage; kein Nachweis einer Originalquelle oder eines Exports."""
from contextlib import closing, contextmanager
from datetime import date
import fcntl
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile

MERCHANTS = ('kaufland', 'dm', 'lidl', 'rossmann')


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        before = os.fstat(source.fileno())
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
        after = os.fstat(source.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Datei wurde während der Prüfung verändert; Eingang bleibt ausstehend.')
    return after.st_size, digest.hexdigest()


def archive_name(merchant, digest, suffix, receipt_id=None, purchase_date=None):
    if merchant not in MERCHANTS or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('Händler oder SHA-256 ungültig.')
    if purchase_date:
        if date.fromisoformat(purchase_date).isoformat() != purchase_date:
            raise ValueError('Einkaufsdatum muss YYYY-MM-DD entsprechen.')
    if not re.fullmatch(r'\.[a-zA-Z0-9]{1,8}', suffix):
        suffix = '.bin'
    identity = hashlib.sha256(receipt_id.encode()).hexdigest()[:16] if receipt_id else 'no-id'
    return f'{purchase_date or "undated"}_{merchant}_{identity}_{digest}{suffix.lower()}'


class Archive:
    def __init__(self, root, originals_root=None):
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.files_root = Path(originals_root).resolve() if originals_root else self.root
        self.section = 'originals' if originals_root else 'received'
        self.files_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database = self.root / 'receipts.sqlite3'
        with closing(self._connect()) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS received_files (
                id INTEGER PRIMARY KEY, merchant TEXT NOT NULL, identity TEXT NOT NULL,
                receipt_id TEXT, purchase_date TEXT, sha256 TEXT NOT NULL,
                byte_count INTEGER NOT NULL, relative_path TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'stored')),
                origin_verified INTEGER NOT NULL DEFAULT 0 CHECK(origin_verified = 0),
                UNIQUE(merchant, identity), UNIQUE(merchant, sha256)
            )''')
            db.commit()
        os.chmod(self.database, 0o600)

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _lock(self):
        with (self.root / 'archive.lock').open('a') as handle:
            os.chmod(handle.name, 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def receive(self, source, merchant, expected_sha256, expected_size,
                receipt_id=None, purchase_date=None):
        """Prüft Kopie gegen Vorgaben. Diese müssen aus dem Transport stammen.

        Ein lokal aus einem unvollständigen Download berechneter Erwartungswert
        beweist dessen Vollständigkeit nicht. Format/Bonzuordnung bleiben offen.
        """
        source = Path(source)
        if not isinstance(expected_size, int) or expected_size <= 0:
            raise ValueError('Eine positive erwartete Dateigröße ist erforderlich.')
        if receipt_id is not None and (not isinstance(receipt_id, str) or not receipt_id.strip()):
            raise ValueError('Bon-ID muss eine nicht leere Zeichenfolge sein oder fehlen.')
        filename = archive_name(merchant, expected_sha256, source.suffix, receipt_id, purchase_date)
        period = (purchase_date[:4], purchase_date[5:7]) if purchase_date else ('unknown', 'unknown')
        relative = Path(self.section, merchant, *period, filename)
        identity = 'id:' + receipt_id if receipt_id else 'sha256:' + expected_sha256
        with self._lock(), closing(self._connect()) as db:
            by_id = db.execute('SELECT * FROM received_files WHERE merchant=? AND identity=?',
                               (merchant, identity)).fetchone()
            by_hash = db.execute('SELECT * FROM received_files WHERE merchant=? AND sha256=?',
                                 (merchant, expected_sha256)).fetchone()
            if by_id and (by_id['sha256'] != expected_sha256 or by_id['byte_count'] != expected_size):
                raise ValueError('Bon-ID bereits mit anderem Inhalt erfasst; nichts überschrieben.')
            if by_hash and by_hash['receipt_id'] and receipt_id and by_hash['receipt_id'] != receipt_id:
                raise ValueError('Identischer Inhalt mit anderer Bon-ID; Zuordnung muss geprüft werden.')
            row = by_id or by_hash
            if row:
                relative = Path(row['relative_path'])
                if row['byte_count'] != expected_size:
                    raise ValueError('Erwartete Größe widerspricht dem vorhandenen Inhalts-Hash.')
                if row['purchase_date'] and purchase_date and row['purchase_date'] != purchase_date:
                    raise ValueError('Widersprüchliches Einkaufsdatum; Zuordnung muss geprüft werden.')
                if not row['receipt_id'] and receipt_id:
                    db.execute('UPDATE received_files SET identity=?, receipt_id=? WHERE id=?',
                               (identity, receipt_id, row['id']))
                    db.commit()
            else:
                db.execute('''INSERT INTO received_files
                    (merchant, identity, receipt_id, purchase_date, sha256, byte_count, relative_path, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')''',
                    (merchant, identity, receipt_id, purchase_date, expected_sha256, expected_size, str(relative)))
                db.commit()
                row = db.execute('SELECT * FROM received_files WHERE merchant=? AND identity=?',
                                 (merchant, identity)).fetchone()
            target = self.files_root / relative
            if not target.resolve().is_relative_to(self.files_root):
                raise ValueError('Archivziel liegt außerhalb der lokalen Ablage.')
            was_stored = row['status'] == 'stored' and target.exists()
            if target.exists():
                if target.is_symlink() or file_digest(target) != (expected_size, expected_sha256):
                    db.execute("UPDATE received_files SET status='pending' WHERE id=?", (row['id'],))
                    db.commit()
                    raise ValueError('Vorhandene Zieldatei stimmt nicht überein; nichts überschrieben.')
            else:
                db.execute("UPDATE received_files SET status='pending' WHERE id=?", (row['id'],))
                db.commit()
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.incoming-', delete=False) as out:
                        temporary = Path(out.name)
                        with source.open('rb') as incoming:
                            for block in iter(lambda: incoming.read(1024 * 1024), b''):
                                out.write(block)
                        out.flush()
                        os.fsync(out.fileno())
                    if file_digest(temporary) != (expected_size, expected_sha256):
                        raise ValueError('Dateieingang unvollständig oder Hash abweichend; bleibt ausstehend.')
                    # Atomare Veröffentlichung ohne Überschreiben; Temp liegt auf demselben Dateisystem.
                    os.link(temporary, target)
                    directory_fd = os.open(target.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                    if file_digest(target) != (expected_size, expected_sha256):
                        raise ValueError('Archivkopie konnte nicht bestätigt werden; bleibt ausstehend.')
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            db.execute("UPDATE received_files SET status='stored' WHERE id=?", (row['id'],))
            db.commit()
            return {'path': target, 'sha256': expected_sha256, 'bytes': expected_size,
                    'already_stored': was_stored, 'origin_verified': False, 'status': 'stored'}
