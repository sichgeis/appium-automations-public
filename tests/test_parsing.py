from pathlib import Path
import tempfile
import unittest
from receiptbot.parsing import cents, parse_text, read_pdf, validate_receipt
from synthetic import TEXT, pdf


class ParsingTests(unittest.TestCase):
    def test_decimal_quantities_discounts_and_sum_checks(self):
        result = parse_text(TEXT, 'kaufland')
        self.assertEqual(result['total_cents'], 380)
        self.assertEqual(result['date'], '2026-10-30')
        self.assertEqual(result['items'][0]['unit_price_cents'], 150)
        self.assertEqual(result['items'][0]['quantity'], '2')
        self.assertEqual(result['items'][1]['quantity'], '0.500')
        self.assertEqual(result['items'][1]['description'], 'Testapfel')
        self.assertEqual(result['items'][2]['kind'], 'discount')
        self.assertEqual(result['warnings'], [])
        self.assertIsNone(result['receipt_id'])
        self.assertEqual(cents('1.234,56'), 123456)

    def test_ambiguity_missing_values_and_sum_mismatch_are_explicit(self):
        result = parse_text(TEXT.replace('Summe 3,80', 'Summe 4,80'), 'kaufland')
        self.assertIn('item_sum_mismatch', result['warnings'])
        self.assertIn('tax_total_mismatch', result['warnings'])
        result = parse_text(TEXT + '\nSumme 9,90\nDatum 31.10.26', 'kaufland')
        self.assertIsNone(result['total_cents'])
        self.assertIsNone(result['date'])
        self.assertFalse(parse_text(TEXT, 'dm')['items'])

    def test_pdf_complete_text_and_receipt_association(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pdf(Path(directory) / 'synthetic.pdf')
            expected = dict(merchant='kaufland', date='2026-10-30', total_cents=380, text=TEXT)
            self.assertEqual(validate_receipt(path, expected)['total_cents'], 380)
            # Gleicher Tag+Betrag reichen ausdrücklich nicht.
            with self.assertRaises(ValueError):
                validate_receipt(path, dict(expected, text=TEXT.replace('Testmilch', 'Andereware')))
            with self.assertRaises(ValueError):
                validate_receipt(path, dict(expected, total_cents=381))
            path.write_bytes(path.read_bytes()[:-8])
            with self.assertRaises(ValueError):
                read_pdf(path)

    def test_unknown_original_format_not_silently_converted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'original.png'
            path.write_bytes(b'\x89PNG\r\n\x1a\n')
            with self.assertRaisesRegex(ValueError, 'kein PDF'):
                read_pdf(path)

    def test_observed_pdf_footer_overrides_card_time_and_scopes_bon_identity(self):
        synthetic_footer = '\nDatum:30.10.26 Zeit:17:54:22 Bon:100001\nFiliale:1000 Kasse:01\n'
        parsed = parse_text(TEXT + synthetic_footer, 'kaufland')
        self.assertEqual(parsed['receipt_id'], '100001')
        self.assertEqual(parsed['branch'], '1000')
        self.assertEqual(parsed['register'], '01')
        self.assertEqual(parsed['time'], '17:54:22')
        self.assertIsNone(parse_text(TEXT + '\nTA-Nr 123 BNr 456', 'kaufland')['receipt_id'])
