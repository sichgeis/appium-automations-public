from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from html import escape
from receiptbot.parsing import parse_text
from receiptbot.adapters.lidl import list_entries
from receiptbot.images import validate_image_receipt, monetary_tokens, captured_app_text

TEXT = '''Teststraße 1
10000 Teststadt
EUR
Testprodukt 2,00 x 2 4,00 A
Preisvorteil -0,50
Lidl Plus Rabatt -0,20
--------------------------------
zu zahlen 3,30
Kreditkarte 3,30
MWST% MWST + Netto = Brutto
A 7 % 0,22 3,08 3,30
TSE Transaktionsnummer: 100001
Seriennr. Kasse: SYNTHETIC-01
Seriennr. TSE: SYNTHETICBASE64
Prüfwert: SYNTHETIC
1000 123456/01 01.02.26 12:34
01.02.2026 12:35 T-ID 12345678
TA-Nr. 123456 Beleg-Nr. 0123
'''


class LidlTests(unittest.TestCase):
    def test_observed_parser_quantities_discounts_taxes_and_identity(self):
        p = parse_text(TEXT,'lidl')
        self.assertEqual(p['total_cents'],330)
        self.assertEqual(p['date'],'2026-02-01')
        self.assertEqual(p['time'],'12:34')
        self.assertEqual(p['items'][0]['quantity'],'2')
        self.assertEqual(p['items'][0]['unit_price_cents'],200)
        self.assertEqual(p['items'][1]['kind'],'discount')
        self.assertEqual(p['taxes'][0]['net_cents'],308)
        self.assertEqual(p['warnings'],[])
        self.assertIsNone(p['receipt_id'])
        self.assertEqual(p['tse_transaction'],'100001')

    def test_list_never_invents_year_and_ambiguity_stops(self):
        label = 'Kassenbon vom 1. Februar über 3,30 €. 2 Produkte gekauft., '
        cell = '<XCUIElementTypeCell type="XCUIElementTypeCell" visible="true" label="' + escape(label,quote=True) + '"/>'
        entries = list_entries('<App>' + cell + '</App>')
        self.assertEqual((entries[0].day,entries[0].month,entries[0].amount),(1,2,330))
        with self.assertRaises(ValueError):
            list_entries('<App>' + cell*2 + '</App>')

    def test_money_fragments_and_locale_are_normalized_without_date_tokens(self):
        self.assertEqual(monetary_tokens('Netto 3, 08 −0,20 01.02.2026'),monetary_tokens('Netto 3.08 -0.20'))

    def image(self,text=TEXT):
        return dict(complete=True,format='public.png',width=100,height=1000,text=text,observations=[])

    def expected(self):
        return dict(merchant='lidl',date='2026-02-01',total_cents=330,text=TEXT)

    def test_image_check_uses_app_fields_and_preserves_bound_source_text(self):
        with patch('receiptbot.images.read_image', return_value=self.image()):
            parsed = validate_image_receipt('synthetic.png',self.expected())
        self.assertEqual(parsed['source_method'],'app_accessibility')
        self.assertEqual(parsed['original_format'],'png')
        self.assertEqual(captured_app_text(parsed),TEXT)
        self.assertTrue(parsed['image_verification']['all_money_values_matched'])
        parsed['source_ui_text'] += 'changed'
        with self.assertRaises(ValueError):
            captured_app_text(parsed)

    def test_image_wrong_amount_missing_date_or_different_text_is_rejected(self):
        for text in (TEXT.replace('3,30','9,90'), TEXT.replace('01.02.2026','02.02.2026').replace('01.02.26','02.02.26'), TEXT.replace('Testprodukt','X').replace('Teststraße','Y').replace('Teststadt','Z').replace('Preisvorteil','Q').replace('Prüfwert','R')):
            with patch('receiptbot.images.read_image', return_value=self.image(text)):
                with self.assertRaises(ValueError):
                    validate_image_receipt('synthetic.png',self.expected())

    def test_all_history_stays_blocked_until_real_year_filter_is_implemented(self):
        from receiptbot.workflow import export_receipts
        with patch('receiptbot.session.session') as session:
            with self.assertRaisesRegex(ValueError,'Jahresfilter'):
                export_receipts({},'lidl',all_receipts=True,approve_large=True)
            session.assert_not_called()

    def test_exact_fiscal_identity_allows_small_ocr_word_variation_but_marks_it(self):
        text = TEXT.replace('Testprodukt','ProduktX')
        with patch('receiptbot.images.read_image', return_value=self.image(text)):
            parsed = validate_image_receipt('synthetic.png',self.expected())
        self.assertTrue(parsed['image_verification']['fiscal_identity_matched'])
        self.assertIn('image_ocr_text_difference',parsed['warnings'])

    def test_conflicting_printed_identity_is_rejected_even_with_nearly_identical_text(self):
        with patch('receiptbot.images.read_image', return_value=self.image(TEXT.replace('100001','100002'))):
            with self.assertRaisesRegex(ValueError,'TSE-/Kassenkennung'):
                validate_image_receipt('synthetic.png',self.expected())

    def test_quantity_price_mismatch_is_explicit(self):
        parsed=parse_text(TEXT.replace('2,00 x 2','2,00 x 3'),'lidl')
        self.assertIn('item_quantity_price_mismatch',parsed['warnings'])

    def test_date_scope_requires_observed_twelve_month_filter_and_recent_cutoff(self):
        from datetime import date
        from receiptbot.adapters.lidl import Lidl
        adapter=Lidl(MagicMock())
        adapter.source=MagicMock(return_value='<App><Cell visible="true" label="Datum: Letzte 12 Monate"/></App>')
        adapter.assert_period_covers(date.today())
        with self.assertRaises(ValueError):adapter.assert_period_covers(date(2000,1,1))
        adapter.source.return_value='<App><Cell visible="true" label="Datum: Benutzerdefiniert"/></App>'
        with self.assertRaises(ValueError):adapter.assert_period_covers(date.today())
