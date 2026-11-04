import csv
from pathlib import Path
import tempfile
import unittest
from receiptbot.bookings import booking_rows, write_bookings
from receiptbot.parsing import parse_text
from receiptbot.quality import flags, audit_file, audit_rows
from synthetic import TEXT


class QualityTests(unittest.TestCase):
    def rows(self, text):
        parsed = dict(parse_text(text, 'kaufland'), sha256='a'*64, source='synthetic.pdf',
                      original_format='pdf', source_method='pdf_text', status='review_required')
        return booking_rows(parsed)

    def test_existing_split_name_bug_is_reproduced_and_audited(self):
        # Absichtlicher Charakterisierungstest des NOCH NICHT reparierten Parsers.
        rows = self.rows(TEXT.replace('Testmilch 2 * 1,50 3,00 B', 'Testmilch\n2 * 1,50 3,00 B'))
        numeric = [r for r in rows if r.get('Item') == '2 * 1,50']
        self.assertEqual(len(numeric), 1)
        self.assertIn('recognized_name_without_letters', flags(numeric[0]))
        self.assertTrue(any(r.get('Originalzeile') == 'Testmilch' and r['Buchungsart'] == 'ungeklaerte_Quellzeile' for r in rows))

    def test_subtotal_and_compensating_row_do_not_make_quality_pass(self):
        rows = self.rows(TEXT.replace('Summe 3,80', 'Zwischensumme 3,80\nSumme 3,80'))
        subtotal = next(r for r in rows if r.get('Item') == 'Zwischensumme')
        self.assertIn('summary_classified_as_position', flags(subtotal))
        self.assertEqual(sum(r.get('Buchungsbetrag_Cent', 0) for r in rows), 380)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'bookings.csv'
            write_bookings(source, rows)
            before = source.read_bytes()
            summary = audit_file(source, Path(tmp)/'quality')
            self.assertEqual(source.read_bytes(), before)
            merchant = summary['merchants']['Kaufland']
            self.assertEqual(merchant['totals_match_including_artificial_rows'], 1)
            self.assertEqual(merchant['recognized_totals_match_without_artificial_rows'], 0)
            self.assertEqual(merchant['issue_rows']['summary_classified_as_position'], 1)
            self.assertEqual(merchant['issue_rows']['artificial_reconciliation_row'], 1)
            with (Path(tmp)/'quality/findings.csv').open() as h:
                self.assertTrue(list(csv.DictReader(h)))

    def test_empty_and_numeric_product_codes_are_not_claimed_invalid(self):
        summary, findings = audit_rows([])
        self.assertEqual((summary['rows'], findings), (0, []))
        row = dict(Zeilenstatus='erkannte_Position', Buchungsart='item', Item='Vitamin B12')
        self.assertEqual(flags(row), [])
        row['Item'] = '12345678'
        self.assertEqual(flags(row), ['recognized_name_without_letters'])
        row['Item'] = ''
        self.assertEqual(flags(row), ['recognized_name_missing'])
