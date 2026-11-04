"""Persistenter Export: selected -> sending -> received -> verified; nie vor Eingang erfolgreich."""
from contextlib import closing
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from uuid import uuid4
from .archive import Archive, file_digest
from .parsing import validate_receipt, normalized, read_pdf, parse_text
from .pdf_identity import receipt_identity, visual_fingerprint
from .transport import snapshot, wait_for_file


def copy_input(source, target, expected):
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or file_digest(target) != expected:
            raise ValueError('Vorhandener Eingang abweichend; nicht überschrieben.')
        return target
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.incoming-', delete=False) as out:
            temporary = Path(out.name)
            with Path(source).open('rb') as incoming:
                for block in iter(lambda: incoming.read(1024 * 1024), b''):
                    out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if file_digest(temporary) != expected:
            raise ValueError('Eingang während Kopieren verändert; nichts übernommen.')
        os.link(temporary, target)
        fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return target
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class Exports:
    def __init__(self, data, output):
        self.data, self.output = Path(data).resolve(), Path(output).resolve()
        self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ('inbox', 'originals', 'processed', 'reports'):
            (self.output / name).mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database = self.data / 'exports.sqlite3'
        with closing(self.connect()) as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS transfers (
                id TEXT PRIMARY KEY, merchant TEXT NOT NULL, state TEXT NOT NULL,
                expected TEXT NOT NULL, baseline TEXT NOT NULL, watch_dir TEXT NOT NULL,
                created TEXT NOT NULL, source TEXT, byte_count INTEGER, sha256 TEXT,
                original TEXT, parsed TEXT);
              CREATE TABLE IF NOT EXISTS originals (
                merchant TEXT NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL,
                byte_count INTEGER NOT NULL, metadata TEXT NOT NULL,
                PRIMARY KEY(merchant, sha256));
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(transfers)')}
            for name, kind in (('archive_sha256', 'TEXT'), ('archive_byte_count', 'INTEGER')):
                if name not in columns:
                    db.execute('ALTER TABLE transfers ADD COLUMN ' + name + ' ' + kind)
            db.commit()
        os.chmod(self.database, 0o600)

    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def prepare(self, expected, directory):
        if self.pending(expected['merchant']):
            raise ValueError('Vorheriger Transfer ausstehend; zuerst Eingang fortsetzen oder bewusst aufgeben.')
        baseline = snapshot(directory)
        if expected.get('transport_kind') == 'icloud':
            name = expected.get('transfer_name', '')
            if not name or Path(name).name != name or name in baseline:
                raise ValueError('Eindeutiger iCloud-Name fehlt oder existiert bereits; nicht speichern/überschreiben.')
        identifier = uuid4().hex
        with closing(self.connect()) as db:
            db.execute('INSERT INTO transfers (id,merchant,state,expected,baseline,watch_dir,created) VALUES (?,?,?,?,?,?,?)',
                (identifier, expected['merchant'], 'sending', json.dumps(expected), json.dumps(baseline),
                 str(Path(directory).resolve()), datetime.now(timezone.utc).isoformat()))
            db.commit()
        return identifier

    def pending(self, merchant):
        with closing(self.connect()) as db:
            return db.execute("SELECT * FROM transfers WHERE merchant=? AND state IN ('sending','received') ORDER BY created LIMIT 1", (merchant,)).fetchone()

    def mark_tapped(self, identifier):
        with closing(self.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS export_taps (transfer_id TEXT PRIMARY KEY, confirmed TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO export_taps VALUES (?,?)',
                       (identifier, datetime.now(timezone.utc).isoformat()))
            db.commit()

    def originals(self):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute('SELECT * FROM originals ORDER BY merchant,sha256')]

    def verified_count(self, merchant):
        count = 0
        for row in self.originals():
            if row['merchant'] == merchant:
                if file_digest(row['path']) != (row['byte_count'], row['sha256']):
                    raise ValueError('Bereits verifiziertes Original verändert; vor weiterem Lauf prüfen.')
                count += 1
        return count

    def abandon_pending(self, merchant):
        with closing(self.connect()) as db:
            db.execute("UPDATE transfers SET state='abandoned' WHERE merchant=? AND state IN ('sending','received')", (merchant,))
            db.commit()

    def same_receipt_original(self, merchant, parsed):
        identity = receipt_identity(parsed)
        if identity is None:
            return None
        matches = []
        for original in self.originals():
            if original['merchant'] != merchant:
                continue
            metadata = json.loads(original['metadata'])
            if receipt_identity(metadata) is None:
                # Ältere, bereits verifizierte Originale können vor dem Footer-Parser liegen.
                if file_digest(original['path']) != (original['byte_count'], original['sha256']):
                    raise ValueError('Vorhandenes Original verändert; Dublettenprüfung angehalten.')
                if metadata.get('original_format') in ('png','jpeg'):
                    from .images import captured_app_text
                    metadata = parse_text(captured_app_text(metadata), merchant)
                else:
                    metadata = parse_text(read_pdf(original['path']), merchant)
            if receipt_identity(metadata) == identity:
                matches.append(original)
        if len(matches) > 1:
            raise ValueError('Mehrere Originale mit derselben belegten Bon-ID; Zuordnung prüfen.')
        return matches[0] if matches else None

    def finish(self, identifier, timeout=90):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM transfers WHERE id=?', (identifier,)).fetchone()
        if row is None or row['state'] not in ('sending', 'received', 'verified'):
            raise ValueError('Unbekannter oder aufgegebener Transfer.')
        expected = json.loads(row['expected'])
        if row['state'] == 'verified':
            archived = (row['archive_byte_count'] or row['byte_count'], row['archive_sha256'] or row['sha256'])
            if file_digest(row['original']) != archived:
                raise ValueError('Früher verifiziertes Original wurde verändert oder fehlt.')
            if file_digest(row['source']) != (row['byte_count'], row['sha256']):
                raise ValueError('Verifizierter Transporteingang fehlt oder wurde verändert.')
            return {'already_stored': True, 'path': Path(row['original']), 'sha256': archived[1], 'bytes': archived[0],
                    'received_sha256': row['sha256'], 'origin_verified': True}
        if row['state'] == 'sending':
            if expected.get('transport_kind') == 'icloud':
                source, size, digest = wait_for_file(row['watch_dir'], json.loads(row['baseline']), timeout,
                    expected_name=expected['transfer_name'], hydrate=True)
            else:
                source, size, digest = wait_for_file(row['watch_dir'], json.loads(row['baseline']), timeout)
            suffix = source.suffix.lower() if source.suffix.lower() in ('.pdf', '.png', '.jpg', '.jpeg', '.html', '.txt') else '.bin'
            with source.open('rb') as handle:
                if handle.read(5) == b'%PDF-':
                    suffix = '.pdf'
            # Inhaltsadressierter Eingang verhindert auch dort wiederholte Kopien.
            target = self.output / 'inbox' / (digest + suffix)
            copy_input(source, target, (size, digest))
            with closing(self.connect()) as db:
                db.execute("UPDATE transfers SET state='received',source=?,byte_count=?,sha256=? WHERE id=?",
                           (str(target), size, digest, identifier))
                db.commit()
        else:
            target, size, digest = Path(row['source']), row['byte_count'], row['sha256']
        if file_digest(target) != (size, digest):
            raise ValueError('Lokaler Eingang verändert. Transfer bleibt unverifiziert.')
        parsed = validate_receipt(target, expected)
        # Bonzähler sind nicht händlerweit eindeutig; nur belegte Filiale/Kasse/Datum bilden die Identität.
        existing = self.same_receipt_original(expected['merchant'], parsed)
        if existing and existing['sha256'] != digest:
            if file_digest(existing['path']) != (existing['byte_count'], existing['sha256']):
                raise ValueError('Vorhandenes Original verändert; keine Dublette bestätigt.')
            old_metadata = json.loads(existing['metadata'])
            if parsed.get('original_format') in ('png','jpeg') and old_metadata.get('original_format') in ('png','jpeg'):
                from .images import captured_app_text
                old_text, new_text = captured_app_text(old_metadata), captured_app_text(parsed)
            else:
                old_text, new_text = read_pdf(existing['path']), read_pdf(target)
            if (normalized(old_text) != normalized(new_text)
                    or visual_fingerprint(existing['path']) != visual_fingerprint(target)):
                raise ValueError('Gleiche Bon-ID mit abweichendem PDF-Inhalt; Originale nicht überschrieben, Eingang bleibt zur Prüfung.')
            result = {'path': Path(existing['path']), 'sha256': existing['sha256'], 'bytes': existing['byte_count'],
                      'already_stored': True, 'origin_verified': True, 'duplicate_by_receipt_id': True}
        else:
            result = Archive(self.data / 'original-archive', originals_root=self.output).receive(target, expected['merchant'], digest, size,
                        receipt_id=receipt_identity(parsed), purchase_date=parsed['date'])
        # Noch einmal Originalbytes und komplette Format-/Bonprüfung vor Erfolgsstatus.
        if file_digest(result['path']) != (result['bytes'], result['sha256']):
            raise ValueError('Originalkopie nicht bytegetreu bestätigt.')
        with closing(self.connect()) as db:
            old = db.execute('SELECT * FROM originals WHERE merchant=? AND sha256=?', (expected['merchant'], result['sha256'])).fetchone()
            db.execute('INSERT OR IGNORE INTO originals VALUES (?,?,?,?,?)',
                (expected['merchant'], result['sha256'], str(result['path']), result['bytes'], json.dumps(parsed)))
            db.execute('UPDATE originals SET metadata=? WHERE merchant=? AND sha256=?',
                (json.dumps(parsed), expected['merchant'], result['sha256']))
            db.execute("UPDATE transfers SET state='verified',original=?,parsed=?,archive_sha256=?,archive_byte_count=? WHERE id=?",
                (str(result['path']), json.dumps(parsed), result['sha256'], result['bytes'], identifier))
            db.commit()
        result.update(already_stored=bool(old), origin_verified=True, received_sha256=digest)
        return result

    def known_ui_original(self, expected):
        """Gedruckte Bon-/Fiskalidentität und vollständigen Inhalt gegen Archiv prüfen."""
        merchant = expected.get('merchant')
        if merchant not in ('kaufland','dm','lidl','rossmann') or expected.get('ui_identity_unavailable'):
            return None
        parsed = parse_text(expected['text'], merchant)
        # Identität darf das tatsächlich beobachtete Listendatum verwenden;
        # validate_receipt bestätigt es anschließend unabhängig am Original.
        if parsed.get('date') is None:
            parsed['date'] = expected['date']
        if receipt_identity(parsed) is None:
            return None
        original = self.same_receipt_original(merchant, parsed)
        if original is None:
            return None
        if file_digest(original['path']) != (original['byte_count'], original['sha256']):
            raise ValueError('Bereits archiviertes Original verändert; bekanntes UI nicht übersprungen.')
        try:
            validate_receipt(original['path'], expected)
        except ValueError:
            # Gleiche Kennung mit anderer Oberfläche ist kein Überspringnachweis.
            return None
        return original

    def adopt_received(self, expected, source):
        """Vom Nutzer bereits gespeicherten Bon prüfen; kein automatischer UI-Nachweis."""
        from .icloud import is_placeholder
        source = Path(source)
        if is_placeholder(source):
            raise ValueError('Manuell gespeicherte Datei ist noch ein iCloud-Platzhalter.')
        parsed = validate_receipt(source, expected)
        size, digest = file_digest(source)
        suffix = {'pdf':'.pdf','png':'.png','jpeg':'.jpeg'}.get(parsed.get('original_format'))
        if not suffix:
            raise ValueError('Originalformat für manuelle Übernahme nicht bestätigt.')
        target = self.output / 'inbox' / (digest + suffix)
        copy_input(source, target, (size, digest))
        identifier = uuid4().hex
        expected = dict(expected, transport_kind='icloud-manual')
        with closing(self.connect()) as db:
            db.execute('''INSERT INTO transfers
                (id,merchant,state,expected,baseline,watch_dir,created,source,byte_count,sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (identifier, expected['merchant'], 'received', json.dumps(expected), json.dumps(snapshot(source.parent)),
                 str(source.parent.resolve()), datetime.now(timezone.utc).isoformat(), str(target), size, digest))
            db.commit()
        return self.finish(identifier)


def mac_name():
    result = subprocess.run(['scutil', '--get', 'ComputerName'], capture_output=True, text=True, timeout=5)
    name = result.stdout.strip()
    if result.returncode or not name:
        raise ValueError('Eigenen Mac-Namen nicht zuverlässig ermittelt; kein AirDrop-Empfänger geraten.')
    return name


def receipt_view_key(expected):
    fields = [expected.get('date'), expected.get('total_cents'), normalized(expected['text'])]
    return hashlib.sha256(json.dumps(fields).encode()).hexdigest()


def export_receipts(config, merchant, limit=1, new_only=False, all_receipts=False, approve_large=False,
                    timeout=90, max_pages=100, abandon=False, transport=None, resume_list=False, since=None):
    from .session import ROOT, session, device_lock, capabilities
    from .server import local_server
    from .adapters import adapter_for
    from .share_sheet import ShareSheetController
    from .icloud import transport_settings
    from .retailers import require_export_implementation, RETAILERS
    require_export_implementation(merchant)
    cutoff = date.fromisoformat(since) if isinstance(since,str) else since
    if cutoff is not None and not isinstance(cutoff,date):
        raise ValueError('Datumsuntergrenze muss YYYY-MM-DD sein.')
    if resume_list and not (all_receipts or cutoff):
        raise ValueError('Aktuelle Listenposition nur zusammen mit --all oder --since fortsetzen.')
    if all_receipts and not RETAILERS[merchant].full_history_implemented:
        raise ValueError('Vollständiger Verlauf/Jahresfilter für diesen Händler noch nicht implementiert; --all bleibt gesperrt.')
    if not 1 <= limit <= 10000 or not 1 <= max_pages <= 1000 or not 1 <= timeout <= 600:
        raise ValueError('Limit, Seitenzahl oder Wartezeit außerhalb des zulässigen Bereichs.')
    capabilities(config, merchant)
    if config['server_url'].rstrip('/') != 'http://127.0.0.1:4723':
        raise ValueError('Automatischer Projektserver benötigt http://127.0.0.1:4723.')
    store = Exports(ROOT / 'data', ROOT / 'output')
    if (all_receipts or limit > 3) and (not approve_large or store.verified_count(merchant) < 3):
        raise ValueError('Großer Lauf erst nach drei verschiedenen verifizierten Originalen und --approve-large-run zulässig.')
    # Separate Prozesssperre schützt auch Dateiwiederaufnahme ohne laufende Gerätesession.
    with device_lock(ROOT / 'data/export-run'):
        if new_only:
            print('Nur neue Originalinhalte ablegen. Ohne belastbare Bon-ID kann erneuter Empfang für den Hashvergleich nötig sein.', flush=True)
        if abandon:
            store.abandon_pending(merchant)
        pending = store.pending(merchant)
        count = 0
        seen_details = set()
        seen_originals = set()
        seen_excluded = set()
        if pending:
            if cutoff and date.fromisoformat(json.loads(pending['expected'])['date']) < cutoff:
                raise ValueError('Ausstehender Transfer liegt vor der Datumsuntergrenze; zuerst gesondert klären.')
            result = store.finish(pending['id'], timeout)
            seen_details.add(receipt_view_key(json.loads(pending['expected'])))
            seen_originals.add(str(result['path']))
            count += 1
            print('Ausstehender Eingang auf dem Mac verifiziert.' if not result['already_stored'] else 'Ausstehender Eingang als Inhaltsdublette bestätigt.', flush=True)
            if not all_receipts and count >= limit:
                return 0
        kind, directory, folder = transport_settings(config, transport)
        name = mac_name() if kind == 'airdrop' else None
        config = dict(config, new_command_timeout=max(300, timeout + 120, config.get('new_command_timeout', 120)))
        stale = 0
        with local_server(), session(config, merchant) as driver:
            adapter = adapter_for(merchant, driver)
            adapter.open_list()
            if (all_receipts or cutoff) and not resume_list:
                adapter.rewind_list()
            if cutoff and merchant == 'lidl':
                adapter.assert_period_covers(cutoff)
            for page in range(max_pages):
                entries = adapter.entries()
                newly_seen = 0
                for entry in entries:
                    hint = getattr(entry,'date',None)
                    if hint is None and isinstance(getattr(entry,'day',None),str):
                        hint = entry.day
                    if cutoff and hint and date.fromisoformat(hint) < cutoff:
                        excluded = repr(entry)
                        if excluded not in seen_excluded:
                            newly_seen += 1
                            seen_excluded.add(excluded)
                        continue
                    expected = adapter.open_receipt(entry)
                    if cutoff and date.fromisoformat(expected['date']) < cutoff:
                        excluded = receipt_view_key(expected)
                        if excluded not in seen_excluded:
                            newly_seen += 1
                            seen_excluded.add(excluded)
                        adapter.close_receipt()
                        continue
                    # Listendatum/Betrag/Artikelanzahl nie als Dublettennachweis benutzen.
                    # Überlappende Scrollseiten erst anhand kompletter Detailinhalte erkennen.
                    detail_key = receipt_view_key(expected)
                    if detail_key in seen_details and not expected.get('ui_identity_unavailable', False):
                        adapter.close_receipt()
                        continue
                    known = store.known_ui_original(expected) if new_only else None
                    if known is not None:
                        original_key = str(known['path'])
                        if original_key not in seen_originals:
                            newly_seen += 1
                            seen_originals.add(original_key)
                        seen_details.add(detail_key)
                        adapter.close_receipt()
                        print('Bon-ID, vollständiger Text und Archivhash bestätigt; kein erneuter Export nötig.', flush=True)
                        continue
                    # Vor Senden speichern. Jeder Fehler danach stoppt den Lauf, keine Klickwiederholung.
                    adapter.share()
                    sheet = ShareSheetController(adapter)
                    if kind == 'icloud':
                        sheet.open_files(folder)
                        expected = dict(expected, transport_kind='icloud', transfer_name='appium-' + uuid4().hex + getattr(adapter,'export_suffix','.pdf'))
                    else:
                        sheet.ensure_mac(name)
                    identifier = store.prepare(expected, directory)
                    if kind == 'icloud':
                        if hasattr(adapter,'export_name_pattern'):
                            sheet.save_file(folder, expected['transfer_name'], adapter.export_name_pattern)
                        else:
                            sheet.save_file(folder, expected['transfer_name'])
                    else:
                        adapter.send_to_mac(name)
                    store.mark_tapped(identifier)
                    print(('In iCloud-Dateien gespeichert angetippt' if kind == 'icloud' else 'AirDrop an eigenen Mac angetippt')
                          + '; lokaler Dateieingang noch ausstehend.', flush=True)
                    result = store.finish(identifier, timeout)
                    seen_details.add(detail_key)
                    original_key = str(result['path'])
                    if original_key not in seen_originals:
                        newly_seen += 1
                        count += 1
                        seen_originals.add(original_key)
                    print('Original auf Mac verifiziert: ' + ('Inhaltsdublette, keine zweite Originalablage.' if result['already_stored'] else 'neu archiviert.'), flush=True)
                    adapter.close_receipt()
                    if not all_receipts and count >= limit:
                        print('Exportlimit erreicht; kein weiterer Bon geöffnet.', flush=True)
                        return 0
                stale = stale + 1 if not newly_seen and page > 0 else 0
                # Zwei unveränderte Seiten nach zwei Scrollversuchen: beobachtetes Ende, keine Server-Vollständigkeitsbehauptung.
                if stale >= 2:
                    print('Listenende nach zwei unveränderten Scrollversuchen. Verarbeitet: ' + str(count), flush=True)
                    return 0
                adapter.scroll()
        raise ValueError('Seitenlimit erreicht; Lauf unvollständig. Bereits verifizierte Originale bleiben erhalten.')
