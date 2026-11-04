from pathlib import Path
from html import escape
import tempfile,unittest
from synthetic import pdf
from receiptbot.parsing import parse_text,validate_receipt
from receiptbot.pdf_identity import receipt_identity
from receiptbot.adapters.rossmann import list_entries,receipt_segments

TEXT='''ROSSMANN
01.02.26, 12:34 / 1000 / 1 / 100 / 0000000001 / 1.0.0
1234567890123 ARTIKEL EINS €6,99 A
-1X D12345 LEERZYLINDER €0,00 C
2X 1234567890124 ARTIKEL ZWEI €2,99 €5,98 A
Zwischensumme: €12,97
Deine Coupon-Ersparnis heute:
1234567890125 10% COUPONAKTION €1,30
----------------
Summe: €11,67
MWST Gruppe Netto MWST Brutto
A 19%: €9,81 €1,86 €11,67
C 0%: €0,00 €0,00 €0,00
Steuerreferenz:
Signaturzähler: 123456
Signatur: SYNTHETICBASE64
SYNTHETICMORE
Start: 2026-02-01T12:34:00+01:00
Ende: 2026-02-01T12:34:00+01:00
'''

class RossmannTests(unittest.TestCase):
    def test_original_layout_returns_discount_tax_and_printed_signature(self):
        for text in (TEXT,TEXT.replace(' ','\ufe0f')):
            p=parse_text(text,'rossmann')
            self.assertEqual(p['warnings'],[])
            self.assertEqual((p['date'],p['total_cents']),('2026-02-01',1167))
            self.assertEqual(len(p['items']),4)
            self.assertEqual(p['items'][-1]['amount_cents'],-130)
            self.assertEqual(p['items'][1]['kind'],'refund')
            self.assertEqual(p['items'][2]['unit_price_cents'],299)
            self.assertIsNone(p['receipt_id'])
            self.assertIsNotNone(receipt_identity(p))

    def test_pdf_requires_all_observed_lines_and_exact_signature(self):
        parts=TEXT.splitlines()[2:]
        expected=dict(merchant='rossmann',date='2026-02-01',total_cents=1167,text='\n'.join(parts),receipt_segments=parts)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bon.pdf';pdf(p,TEXT)
            self.assertEqual(validate_receipt(p,expected)['original_format'],'pdf')
            for text in (TEXT.replace('SYNTHETICMORE','DIFFERENT'),TEXT.replace('ARTIKEL EINS','OTHER PRODUCT'),TEXT.replace('€11,67','€11,68')):
                pdf(p,text)
                with self.assertRaises(ValueError):validate_receipt(p,expected)

    def test_duplicate_day_blocks_ambiguous_navigation(self):
        row='<Node type="XCUIElementTypeStaticText" visible="true" label="Einkauf vom 01.02.26"/><Node type="XCUIElementTypeStaticText" label="11,67 €"/>'
        self.assertEqual(list_entries('<App>'+row+'</App>')[0].amount,1167)
        with self.assertRaises(ValueError):list_entries('<App>'+row*2+'</App>')
        self.assertIsNone(receipt_segments('<App/>'))

    def test_unknown_zero_value_item_and_discount_are_not_silently_lost(self):
        p=parse_text(TEXT.replace('Zwischensumme:', '1234567890126 UNBEKANNT\nZwischensumme:').replace('----------------','UNKNOWN DISCOUNT'),'rossmann')
        self.assertIn('unparsed_item_line',p['warnings'])
        self.assertIn('unparsed_discount_line',p['warnings'])

    def test_date_amount_alone_never_form_receipt_identity(self):
        p=parse_text(TEXT,'rossmann');p.pop('fiscal_signature')
        self.assertIsNone(receipt_identity(p))

    def test_starred_amount_before_tax_code_is_still_an_exact_item(self):
        p=parse_text(TEXT.replace('€6,99 A','€6,99*A'),'rossmann')
        self.assertEqual(p['warnings'],[])
        self.assertEqual(p['items'][0]['amount_cents'],699)
        self.assertIn('*',p['items'][0]['raw_line'])

    def test_discount_summary_is_not_a_second_discount_and_mismatch_is_flagged(self):
        p=parse_text(TEXT.replace('----------------','Du hast insgesamt €1,30 gespart!'),'rossmann')
        self.assertEqual(p['warnings'],[])
        self.assertEqual(len(p['items']),4)
        bad=parse_text(TEXT.replace('----------------','Du hast insgesamt €1,31 gespart!'),'rossmann')
        self.assertIn('discount_sum_mismatch',bad['warnings'])

    def test_discount_in_explicit_savings_block_can_have_no_printed_article_code(self):
        p=parse_text(TEXT.replace('1234567890125 10% COUPONAKTION','10% COUPONAKTION'),'rossmann')
        self.assertEqual(p['warnings'],[])
        self.assertEqual(p['items'][-1]['amount_cents'],-130)
        self.assertEqual(p['items'][-1]['description'],'10% COUPONAKTION')
