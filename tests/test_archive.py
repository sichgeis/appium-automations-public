from contextlib import closing, contextmanager
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from receiptbot.archive import Archive, archive_name


@contextmanager
def database(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'synthetic.bin'
        self.content = b'SYNTHETIC RECEIPT INPUT\n'
        self.source.write_bytes(self.content)
        self.sha = hashlib.sha256(self.content).hexdigest()
        self.archive = Archive(self.root / 'data')

    def receive(self, **kwargs):
        return self.archive.receive(self.source, 'kaufland', self.sha, len(self.content), **kwargs)

    def test_preserves_bytes_and_deduplicates_after_reopening(self):
        first = self.receive(receipt_id='SYNTHETIC-1')
        self.archive = Archive(self.root / 'data')
        second = self.receive(receipt_id='SYNTHETIC-1')
        self.assertEqual(first['path'].read_bytes(), self.content)
        self.assertEqual(self.source.read_bytes(), self.content)
        self.assertEqual(first['path'], second['path'])
        self.assertTrue(second['already_stored'])
        self.assertFalse(second['origin_verified'])
        self.assertEqual(len(list((self.root / 'data/received').rglob('*.bin'))), 1)

    def test_hash_dedup_without_id_and_separate_merchants(self):
        first = self.receive()
        self.assertTrue(self.receive()['already_stored'])
        second = self.archive.receive(self.source, 'dm', self.sha, len(self.content))
        self.assertNotEqual(first['path'], second['path'])

    def test_incomplete_transfer_stays_pending_and_resumes(self):
        self.source.write_bytes(self.content[:8])
        with self.assertRaises(ValueError):
            self.receive(receipt_id='SYNTHETIC-2')
        with database(self.archive.database) as db:
            self.assertEqual(db.execute('SELECT status FROM received_files').fetchone()[0], 'pending')
        self.assertFalse(list((self.root / 'data').rglob('.incoming-*')))
        self.source.write_bytes(self.content)
        self.assertEqual(self.receive(receipt_id='SYNTHETIC-2')['status'], 'stored')

    def test_resume_when_file_published_but_database_commit_failed(self):
        with database(self.archive.database) as db:
            db.execute("CREATE TRIGGER simulate_failure BEFORE UPDATE ON received_files WHEN NEW.status='stored' BEGIN SELECT RAISE(FAIL, 'synthetic interruption'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.receive(receipt_id='SYNTHETIC-3')
        self.assertEqual(len(list((self.root / 'data/received').rglob('*.bin'))), 1)
        with database(self.archive.database) as db:
            self.assertEqual(db.execute('SELECT status FROM received_files').fetchone()[0], 'pending')
            db.execute('DROP TRIGGER simulate_failure')
        result = self.receive(receipt_id='SYNTHETIC-3')
        self.assertFalse(result['already_stored'])
        self.assertEqual(result['path'].read_bytes(), self.content)

    def test_existing_receipt_id_never_overwritten_by_different_content(self):
        first = self.receive(receipt_id='SYNTHETIC-4')
        other = b'DIFFERENT INPUT'
        self.source.write_bytes(other)
        with self.assertRaises(ValueError):
            self.archive.receive(self.source, 'kaufland', hashlib.sha256(other).hexdigest(),
                                 len(other), receipt_id='SYNTHETIC-4')
        self.assertEqual(first['path'].read_bytes(), self.content)

    def test_conflicting_receipt_ids_for_identical_content_require_review(self):
        self.receive(receipt_id='SYNTHETIC-5')
        with self.assertRaises(ValueError):
            self.receive(receipt_id='SYNTHETIC-6')

    def test_modified_archive_is_detected_and_not_overwritten(self):
        result = self.receive()
        result['path'].write_bytes(b'EXTERNAL CHANGE')
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(result['path'].read_bytes(), b'EXTERNAL CHANGE')
        with database(self.archive.database) as db:
            self.assertEqual(db.execute('SELECT status FROM received_files').fetchone()[0], 'pending')

    def test_receipt_id_can_be_added_after_hash_only_receipt(self):
        first = self.receive()
        identified = self.receive(receipt_id='SYNTHETIC-LATE-ID')
        self.assertEqual(first['path'], identified['path'])
        self.source.write_bytes(b'OTHER')
        with self.assertRaises(ValueError):
            self.archive.receive(self.source, 'kaufland', hashlib.sha256(b'OTHER').hexdigest(),
                                 5, receipt_id='SYNTHETIC-LATE-ID')

    def test_missing_archived_file_is_repaired_and_failed_repair_is_pending(self):
        result = self.receive()
        result['path'].unlink()
        self.source.write_bytes(b'SHORT')
        with self.assertRaises(ValueError):
            self.receive()
        with database(self.archive.database) as db:
            self.assertEqual(db.execute('SELECT status FROM received_files').fetchone()[0], 'pending')
        self.source.write_bytes(self.content)
        self.assertFalse(self.receive()['already_stored'])

    def test_same_size_corruption_rejected(self):
        self.source.write_bytes(b'X' * len(self.content))
        with self.assertRaises(ValueError):
            self.receive()

    def test_safe_deterministic_filename_and_missing_metadata(self):
        name = archive_name('kaufland', self.sha, '.PDF', '../../sensitive/id', '2026-10-31')
        self.assertNotIn('sensitive', name)
        self.assertNotIn('/', name)
        self.assertEqual(name, archive_name('kaufland', self.sha, '.PDF', '../../sensitive/id', '2026-10-31'))
        result = self.receive()
        self.assertIn('unknown/unknown', str(result['path']))

    def test_rejects_bad_merchant_hash_date_and_empty_file(self):
        for merchant, digest, suffix, identifier, day in [
            ('../escape', self.sha, '.bin', None, None),
            ('kaufland', '../escape', '.bin', None, None),
            ('kaufland', self.sha, '.bin', None, '2026-13-01'),
            ('kaufland', self.sha, '.bin', None, '20261031'),
        ]:
            with self.assertRaises(ValueError):
                archive_name(merchant, digest, suffix, identifier, day)
        with self.assertRaises(ValueError):
            self.archive.receive(self.source, 'kaufland', self.sha, 0)
