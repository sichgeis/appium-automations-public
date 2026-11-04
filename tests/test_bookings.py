import csv
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from receiptbot.bookings import booking_rows, write_bookings
from receiptbot.parsing import parse_text
from receiptbot.reporting import report
from synthetic import TEXT


class BookingTests(unittest.TestCase):
    def parsed(self, text=TEXT, merchant='kaufland'):
        return dict(parse_text(text, merchant), sha256='a'*64, source='synthetic.pdf',
                    original_format='pdf', source_method='pdf_text', status='parsed')

    def test_discount_not_allocated_or_double_counted_and_missing_values_blank(self):
        rows = booking_rows(self.parsed())
        self.assertEqual(sum(r['Buchungsbetrag_Cent'] for r in rows), 380)
        self.assertEqual(rows[-1]['Rabatt_Cent'], 20)
        self.assertIsNone(rows[0]['Rabatt_Cent'])
        self.assertEqual(rows[0]['Menge'], '2')
        self.assertEqual(rows[0]['Steuersatz_Prozent'], '7.00')
        self.assertIsNone(rows[1]['Einzelpreis_Cent'])
        self.assertEqual(rows[0]['Filiale_Status'], 'nicht_extrahiert')
        self.assertIsNone(rows[0]['Bon_ID'])
        self.assertFalse(any(r['Buchungsart'] == 'Pruefdifferenz' for r in rows))

    def test_unknown_lines_and_signed_reconciliation_not_fake_items(self):
        p = self.parsed(TEXT.replace('Preis EUR', 'Preis EUR\nUnbekannter Artikel').replace('Summe 3,80','Summe 4,30'))
        rows = booking_rows(p)
        unknown = [r for r in rows if r['Buchungsart'] == 'ungeklaerte_Quellzeile']
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]['Originalzeile'], 'Unbekannter Artikel')
        self.assertNotIn('Buchungsbetrag_Cent', unknown[0])
        self.assertEqual(rows[-1]['Buchungsbetrag_Cent'], 50)
        self.assertEqual(rows[-1]['Buchungsart'], 'Pruefdifferenz')
        self.assertEqual(sum(r.get('Buchungsbetrag_Cent', 0) for r in rows), 430)
        negative = booking_rows(self.parsed(TEXT.replace('Summe 3,80','Summe 3,30')))
        self.assertEqual(negative[-1]['Buchungsbetrag_Cent'], -50)

    def test_weight_continuation_is_not_an_unknown_line(self):
        self.assertEqual(self.parsed()['unparsed_lines'], [])
        p = self.parsed(TEXT.replace('K Card XTRA Rabatt -0,20','K Card XTRA Rabatt -0,20\nUNBEKANNT'))
        self.assertEqual(p['unparsed_lines'], ['UNBEKANNT'])

    def test_unparsed_lines_preserved_for_all_other_merchants(self):
        from test_dm import TEXT as DM
        from test_lidl import TEXT as LIDL
        from test_rossmann import TEXT as ROSSMANN
        fixtures = [
            ('dm', DM.replace('Testartikel 1,00 1', 'UNBEKANNT')),
            ('lidl', LIDL.replace('EUR\n', 'EUR\nUNBEKANNT\n', 1)),
            ('rossmann', ROSSMANN.replace('Zwischensumme:', '1234567890126 UNBEKANNT\nZwischensumme:')),
        ]
        for merchant, text in fixtures:
            with self.subTest(merchant=merchant):
                p = self.parsed(text, merchant)
                self.assertEqual(len(p['unparsed_lines']), 1)
                rows = booking_rows(p)
                self.assertTrue(any(r['Buchungsart'] == 'ungeklaerte_Quellzeile' for r in rows))
                self.assertEqual(sum(r.get('Buchungsbetrag_Cent', 0) for r in rows), p['total_cents'])

    def test_empty_receipt_and_unknown_total_remain_visible(self):
        p = self.parsed()
        p.update(items=[], total_cents=None)
        rows = booking_rows(p)
        self.assertEqual(rows[0]['Buchungsart'], 'Bon_ohne_Positionen')
        self.assertIsNone(rows[0]['Bon_Gesamtsumme_Cent'])

    def test_german_csv_roundtrip_formula_protection_and_deterministic_update(self):
        p = self.parsed()
        p['items'][0]['description'] = '=HYPERLINK("bad"); Äpfel\nZweite Zeile'
        p['branch'] = '01234'
        rows = booking_rows(p)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'buchungen.csv'
            write_bookings(path, rows)
            first = path.read_bytes()
            self.assertTrue(first.startswith(b'\xef\xbb\xbf'))
            with path.open(encoding='utf-8-sig', newline='') as h:
                read = list(csv.DictReader(h, delimiter=';'))
            self.assertEqual(len(read), 3)
            self.assertTrue(read[0]['Item'].startswith("'="))
            self.assertEqual(read[0]['Filiale'], '01234')
            self.assertEqual(read[-1]['Buchungsbetrag'], '-0,20')
            self.assertEqual(read[-1]['Rabatt'], '0,20')
            self.assertEqual(sum(Decimal(r['Buchungsbetrag'].replace(',', '.')) for r in read), Decimal('3.80'))
            write_bookings(path, list(reversed(rows)))
            self.assertEqual(path.read_bytes(), first)

    def test_invalid_numeric_formula_cannot_escape(self):
        rows = booking_rows(self.parsed())
        rows[0]['Menge'] = '=2+2'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'buchungen.csv'
            path.write_bytes(b'previous')
            with self.assertRaises(Exception):
                write_bookings(path, rows)
            self.assertEqual(path.read_bytes(), b'previous')

    def test_report_integration_empty_archive_has_header_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertEqual(report(base/'data', base/'output'), (0, 0))
            with (base/'output/reports/buchungen.csv').open(encoding='utf-8-sig') as h:
                reader = csv.DictReader(h, delimiter=';')
                self.assertIn('Rabatt', reader.fieldnames)
                self.assertEqual(list(reader), [])

    def test_bookings_cli_is_offline(self):
        from receiptbot.__main__ import main
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp, patch('receiptbot.__main__.ROOT', Path(tmp)), \
             patch('sys.argv', ['receiptbot', 'bookings']), patch('receiptbot.__main__.load_config', side_effect=AssertionError), \
             redirect_stdout(StringIO()):
            self.assertEqual(main(), 0)
            self.assertTrue((Path(tmp)/'output/reports/buchungen.csv').is_file())
