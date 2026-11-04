from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from receiptbot.archive import file_digest
from receiptbot.transport import snapshot, wait_for_file
from receiptbot.workflow import Exports
from receiptbot.reporting import report
from synthetic import TEXT, pdf


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.downloads = self.root / 'Downloads'
        self.downloads.mkdir()
        self.store = Exports(self.root / 'data', self.root / 'output')
        self.expected = dict(merchant='kaufland', date='2026-10-30', total_cents=380, text=TEXT, navigation_key='synthetic')

    def test_old_file_and_partial_file_never_received(self):
        (self.downloads / 'old.pdf').write_bytes(b'old')
        baseline = snapshot(self.downloads)
        (self.downloads / 'new.pdf.download').write_bytes(b'partial')
        with self.assertRaises(ValueError):
            wait_for_file(self.downloads, baseline, timeout=.03, stable_seconds=0)

    def test_ambiguous_candidates_and_symlinks(self):
        baseline = snapshot(self.downloads)
        (self.downloads / 'a.pdf').write_bytes(b'a')
        (self.downloads / 'b.pdf').write_bytes(b'b')
        with self.assertRaisesRegex(ValueError, 'Mehrere'):
            wait_for_file(self.downloads, baseline, timeout=.03, stable_seconds=0)
        (self.downloads / 'link.pdf').symlink_to(self.downloads / 'a.pdf')
        self.assertNotIn('link.pdf', snapshot(self.downloads))

    def test_timeout_resume_verified_bytes_and_content_dedup(self):
        identifier = self.store.prepare(self.expected, self.downloads)
        with self.assertRaises(ValueError):
            self.store.finish(identifier, timeout=.03)
        self.assertEqual(self.store.pending('kaufland')['state'], 'sending')
        source = pdf(self.downloads / 'received.pdf')
        stable_wait = lambda directory, baseline, timeout: (source, *file_digest(source))
        with patch('receiptbot.workflow.wait_for_file', side_effect=stable_wait):
            result = self.store.finish(identifier)
        self.assertTrue(result['origin_verified'])
        self.assertEqual(result['path'].read_bytes(), source.read_bytes())
        self.assertIn('/originals/kaufland/2026/10/', str(result['path']))
        self.assertIsNone(self.store.pending('kaufland'))
        self.assertEqual(self.store.verified_count('kaufland'), 1)
        other = self.store.prepare(self.expected, self.downloads)
        with patch('receiptbot.workflow.wait_for_file', side_effect=stable_wait):
            self.assertTrue(self.store.finish(other)['already_stored'])
        self.assertEqual(len(list((self.root / 'output/originals').rglob('*.pdf'))), 1)
        self.assertEqual(report(self.root / 'data', self.root / 'output'), (1, 3))
        self.assertIn('2026-10,kaufland,EUR,380', (self.root / 'output/reports/monthly.csv').read_text())

    def test_wrong_receipt_stays_received_and_originals_empty(self):
        identifier = self.store.prepare(self.expected, self.downloads)
        source = pdf(self.downloads / 'wrong.pdf', TEXT.replace('Testmilch', 'Falscher Artikel'))
        with patch('receiptbot.workflow.wait_for_file', return_value=(source, *file_digest(source))):
            with self.assertRaises(ValueError):
                self.store.finish(identifier)
        self.assertEqual(self.store.pending('kaufland')['state'], 'received')
        self.assertEqual(self.store.verified_count('kaufland'), 0)
        self.assertTrue(list((self.root / 'output/inbox').iterdir()))
        with self.assertRaises(ValueError):
            self.store.prepare(self.expected, self.downloads)

    def test_resume_after_original_publish_before_commit(self):
        identifier = self.store.prepare(self.expected, self.downloads)
        source = pdf(self.downloads / 'received.pdf')
        with closing(self.store.connect()) as db:
            db.execute("CREATE TRIGGER interrupt BEFORE UPDATE ON transfers WHEN NEW.state='verified' BEGIN SELECT RAISE(FAIL,'synthetic interruption'); END")
            db.commit()
        with patch('receiptbot.workflow.wait_for_file', return_value=(source, *file_digest(source))):
            with self.assertRaises(Exception):
                self.store.finish(identifier)
        self.assertEqual(self.store.pending('kaufland')['state'], 'received')
        with closing(self.store.connect()) as db:
            db.execute('DROP TRIGGER interrupt')
            db.commit()
        self.store.finish(identifier)
        self.assertEqual(self.store.verified_count('kaufland'), 1)
        self.assertEqual(len(list((self.root / 'output/originals').rglob('*.pdf'))), 1)

    def test_modified_original_stops_reports(self):
        identifier = self.store.prepare(self.expected, self.downloads)
        source = pdf(self.downloads / 'received.pdf')
        with patch('receiptbot.workflow.wait_for_file', return_value=(source, *file_digest(source))):
            result = self.store.finish(identifier)
        result['path'].write_bytes(b'changed')
        with self.assertRaises(ValueError):
            report(self.root / 'data', self.root / 'output')

    def test_growing_transfer_is_not_accepted_at_first_nonzero_size(self):
        import threading
        import time
        baseline = snapshot(self.downloads)
        source = self.downloads / 'growing.pdf'
        source.write_bytes(b'PARTIAL')
        def complete():
            time.sleep(.3)
            source.write_bytes(b'COMPLETE SYNTHETIC TRANSFER')
        thread = threading.Thread(target=complete)
        thread.start()
        self.addCleanup(thread.join)
        path, size, digest = wait_for_file(self.downloads, baseline, timeout=3, stable_seconds=.4)
        self.assertEqual(size, len(b'COMPLETE SYNTHETIC TRANSFER'))
        self.assertEqual((size, digest), file_digest(path))

    def known_original_fixture(self):
        text=TEXT+'Datum: 30.10.26 Zeit: 12:34:00 Bon: 1000\nFiliale: 1000 Kasse: 1\n'
        expected=dict(self.expected,text=text,ui_identity_unavailable=False)
        source=pdf(self.downloads/'identified.pdf',text)
        identifier=self.store.prepare(expected,self.downloads)
        with patch('receiptbot.workflow.wait_for_file',return_value=(source,*file_digest(source))):
            result=self.store.finish(identifier)
        return expected,result

    def test_known_ui_requires_printed_identity_exact_text_and_unchanged_archive(self):
        expected,result=self.known_original_fixture()
        known=self.store.known_ui_original(expected)
        self.assertEqual(known['path'],str(result['path']))
        self.assertIsNone(self.store.known_ui_original(dict(expected,text=expected['text'].replace('Testmilch','Different product'))))
        self.assertIsNone(self.store.known_ui_original(dict(expected,ui_identity_unavailable=True)))
        self.assertIsNone(self.store.known_ui_original(self.expected))
        result['path'].write_bytes(b'changed')
        with self.assertRaises(ValueError):self.store.known_ui_original(expected)
