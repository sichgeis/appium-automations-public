from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from receiptbot.workflow import Exports
from receiptbot.archive import file_digest
from receiptbot.pdf_identity import visual_fingerprint
from synthetic import TEXT, pdf

FOOTER = '\nDatum:30.10.26 Zeit:17:54:22 Bon:100001\nFiliale:1000 Kasse:01\n'


class PdfIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Exports(self.root / 'data', self.root / 'output')

    def adopt(self, label, text=TEXT + FOOTER):
        source = pdf(self.root / (label + '.pdf'), text, {'/CreationDate': label})
        expected = dict(merchant='kaufland',date='2026-10-30',total_cents=380,text=text)
        return source, expected

    def test_metadata_variant_keeps_one_canonical_original_and_both_raw_inputs(self):
        a, ea = self.adopt('synthetic-A')
        first = self.store.adopt_received(ea, a)
        # Früher verifizierte Originale hatten noch keine Footer-Metadaten im Register.
        with closing(self.store.connect()) as db:
            db.execute("UPDATE originals SET metadata='{}'")
            db.commit()
        b, eb = self.adopt('synthetic-B')
        self.assertNotEqual(file_digest(a), file_digest(b))
        with patch('receiptbot.workflow.visual_fingerprint', return_value=('SYNTHETIC-PIXELS',)):
            second = self.store.adopt_received(eb, b)
        self.assertTrue(second['duplicate_by_receipt_id'])
        self.assertEqual(first['path'], second['path'])
        self.assertEqual(first['path'].read_bytes(), a.read_bytes())
        self.assertEqual(self.store.verified_count('kaufland'), 1)
        self.assertEqual(len(list((self.root / 'output/inbox').glob('*.pdf'))), 2)
        with closing(self.store.connect()) as db:
            row = db.execute('SELECT * FROM transfers WHERE sha256=?', (file_digest(b)[1],)).fetchone()
        resumed = self.store.finish(row['id'])
        self.assertEqual(resumed['sha256'], file_digest(a)[1])
        self.assertEqual(resumed['received_sha256'], file_digest(b)[1])
        self.assertEqual(Path(row['source']).read_bytes(), b.read_bytes())

    def test_same_id_with_changed_text_is_not_silently_deduplicated(self):
        a, expected = self.adopt('synthetic-A')
        first = self.store.adopt_received(expected, a)
        b, eb = self.adopt('synthetic-B', (TEXT + FOOTER).replace('Testmilch','Andere Milch'))
        with self.assertRaisesRegex(ValueError, 'abweichendem PDF-Inhalt'):
            self.store.adopt_received(eb, b)
        self.assertEqual(self.store.pending('kaufland')['state'], 'received')
        self.assertEqual(first['path'].read_bytes(), a.read_bytes())

    def test_same_text_with_changed_rendering_still_requires_review(self):
        a, ea = self.adopt('synthetic-A')
        self.store.adopt_received(ea, a)
        b, eb = self.adopt('synthetic-B')
        with patch('receiptbot.workflow.visual_fingerprint', side_effect=[('A',),('B',)]):
            with self.assertRaises(ValueError):
                self.store.adopt_received(eb, b)
        self.assertEqual(self.store.verified_count('kaufland'), 1)

    def test_same_bon_number_in_other_branch_is_a_different_receipt(self):
        a, ea = self.adopt('synthetic-A')
        self.store.adopt_received(ea, a)
        b, eb = self.adopt('synthetic-B', (TEXT + FOOTER).replace('Filiale:1000','Filiale:1001'))
        self.store.adopt_received(eb, b)
        self.assertEqual(self.store.verified_count('kaufland'), 2)

    def test_no_qualified_id_does_not_deduplicate_on_day_amount_or_text(self):
        for label in ('synthetic-A','synthetic-B'):
            source, expected = self.adopt(label, TEXT)
            self.store.adopt_received(expected, source)
        self.assertEqual(self.store.verified_count('kaufland'), 2)

    def test_missing_local_renderer_stops_variant_comparison(self):
        source, _ = self.adopt('synthetic-no-renderer')
        with patch('receiptbot.pdf_identity.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'pdftoppm'):
                visual_fingerprint(source)

    def test_existing_verified_transfer_survives_archive_hash_schema_upgrade(self):
        source, expected = self.adopt('synthetic-old-schema')
        result = self.store.adopt_received(expected, source)
        with closing(self.store.connect()) as db:
            identifier = db.execute('SELECT id FROM transfers').fetchone()[0]
            db.execute('ALTER TABLE transfers DROP COLUMN archive_sha256')
            db.execute('ALTER TABLE transfers DROP COLUMN archive_byte_count')
            db.commit()
        reopened = Exports(self.root / 'data', self.root / 'output')
        resumed = reopened.finish(identifier)
        self.assertEqual(resumed['path'], result['path'])
        self.assertEqual(resumed['sha256'], file_digest(source)[1])
        self.assertEqual(reopened.verified_count('kaufland'), 1)
