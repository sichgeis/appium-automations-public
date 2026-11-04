from unittest.mock import MagicMock
import unittest,tempfile
from pathlib import Path
from html import escape
from synthetic import pdf
from receiptbot.parsing import parse_text,validate_receipt
from receiptbot.adapters.dm import list_entries,quicklook_segments

TEXT='''01.02.2026 12:34 TEST/7 000001/01 1000
Testartikel 1,00 1
2x 2,00 Andere Ware 4,00 1
SUMME EUR 5,00
MwSt-Satz Brutto Netto MwSt
1=19,00% 5,00 4,20 0,80
Öffnungszeiten auf dm.de
SN-Kasse: SYNTHETIC TA-Nummer: 123456
SN-TSE: abcdef0123456789
0123456789abcdef
Signaturzähler: 1000
'''

class DmTests(unittest.TestCase):
    def test_dm_layout_and_fiscal_identity(self):
        p=parse_text(TEXT,'dm')
        self.assertEqual((p['date'],p['total_cents'],len(p['items'])),('2026-02-01',500,2))
        self.assertEqual(p['warnings'],[])
        self.assertEqual(p['items'][1]['quantity'],'2')
        self.assertIsNone(p['receipt_id'])
        self.assertEqual(p['tse_serial'],'abcdef01234567890123456789abcdef')

    def test_reordered_quicklook_segments_require_every_segment_and_all_fiscal_fields(self):
        parts=[TEXT.splitlines()[0],TEXT.splitlines()[1],TEXT[TEXT.index('SN-Kasse:'):]]
        expected=dict(merchant='dm',date='2026-02-01',total_cents=500,text='\n'.join(parts),quicklook_segments=parts)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'original.pdf';pdf(p,TEXT)
            self.assertEqual(validate_receipt(p,expected)['original_format'],'pdf')
            for replacement in ('SN-Kasse:','Not in original'):
                changed=list(parts)
                changed[-1]=changed[-1].replace('SN-Kasse:',replacement+' altered')
                bad=dict(expected,text='\n'.join(changed),quicklook_segments=changed)
                with self.assertRaises(ValueError):validate_receipt(p,bad)
            noidentity=parts[:2]+['Text without printed fiscal identifiers'*4]
            with self.assertRaises(ValueError):validate_receipt(p,dict(expected,text='\n'.join(noidentity),quicklook_segments=noidentity))

    def test_only_observed_store_receipt_links_and_ambiguity_stops(self):
        label='Im Markt eingekauft, Am 01.02.2026, 5,00 €'
        cell='<Node type="XCUIElementTypeLink" visible="true" label="'+escape(label,quote=True)+'"/>'
        self.assertEqual(list_entries('<App>'+cell+'</App>')[0].amount,500)
        with self.assertRaises(ValueError):list_entries('<App>'+cell*2+'</App>')
        self.assertEqual(list_entries('<App><Node type="XCUIElementTypeLink" visible="true" label="Bestellt am 01.02.2026"/></App>'),[])

    def test_quicklook_without_fiscal_identity_stops(self):
        self.assertIsNone(quicklook_segments('<App><Node name="QLPDFViewControllerViewAccessibilityIdentifier"><Node type="XCUIElementTypeStaticText" visible="true" label="'+('A'*100)+'"/></Node></App>'))

    def test_item_and_tax_mismatch_are_visible(self):
        p=parse_text(TEXT.replace('2x 2,00','2x 3,00').replace('4,20 0,80','4,20 0,70'),'dm')
        self.assertIn('item_quantity_price_mismatch',p['warnings'])
        self.assertIn('tax_sum_mismatch',p['warnings'])

    def column_fixture(self):
        text=TEXT.replace('Testartikel 1,00 1','Testartikel 1,00 §1').replace(
            'SUMME EUR 5,00',
            'Zwischensumme 5,00\ndm-Rabatte auf rabattfähige Artikel\n2 x Coupon Test -0,50\nSUMME EUR 4,50').replace(
            '1=19,00% 5,00 4,20 0,80','1=19,00% 4,50 3,78 0,72')
        table='''Testartikel 2x 2,00 Andere Ware 1,00 §1
4,00 1
Zwischensumme 5,00
dm-Rabatte auf rabattfähige Artikel
2 x Coupon Test -0,50
SUMME EUR 4,50'''
        parts=[text.splitlines()[0],table,text[text.index('SN-Kasse:'):]]
        return text,dict(merchant='dm',date='2026-02-01',total_cents=450,text='\n'.join(parts),quicklook_segments=parts)

    def test_actual_column_order_variation_preserves_all_words_amounts_and_markers(self):
        text,expected=self.column_fixture()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bon.pdf';pdf(p,text)
            result=validate_receipt(p,expected)
        self.assertEqual(result['warnings'],[])
        self.assertEqual(len(result['items']),3)
        self.assertTrue(result['items'][0]['discount_excluded'])
        self.assertEqual(result['items'][0]['tax_code'],'1')
        self.assertEqual(result['items'][-1]['kind'],'discount')
        self.assertEqual(result['items'][-1]['amount_cents'],-50)

    def test_column_matching_never_drops_amounts_markers_or_repeated_tokens(self):
        from receiptbot.parsers.dm import quicklook_segment_matches
        text,expected=self.column_fixture()
        table=expected['quicklook_segments'][1]
        for bad in (table.replace('1,00','1,01'),table.replace('§1','1'),
                    table.replace('4,00 1','4,00'),table.replace('Andere Ware','Other Goods')):
            self.assertFalse(quicklook_segment_matches(bad,text))
        # Gleiche Wörter verstreut über das PDF genügen nicht: ein zusammenhängendes
        # Fenster muss exakt dieselben Token und Häufigkeiten enthalten.
        self.assertFalse(quicklook_segment_matches(table,text.replace('Andere Ware','Andere EXTRA Ware')))

    def test_column_matching_requires_explicit_table_total(self):
        from receiptbot.parsers.dm import quicklook_segment_matches
        text,expected=self.column_fixture()
        self.assertFalse(quicklook_segment_matches(expected['quicklook_segments'][1].replace('SUMME EUR','SUM TOTAL'),text))

    def test_column_order_never_bypasses_exact_fiscal_identity(self):
        text,expected=self.column_fixture()
        changed=text.replace('TA-Nummer: 123456','TA-Nummer: 999999')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bon.pdf';pdf(p,changed)
            with self.assertRaises(ValueError):validate_receipt(p,expected)

    def test_dm_subtotal_and_positive_discount_remain_explicit_review_flags(self):
        text,_=self.column_fixture()
        bad=parse_text(text.replace('Zwischensumme 5,00','Zwischensumme 5,01').replace('Test -0,50','Test 0,50'),'dm')
        self.assertIn('subtotal_mismatch',bad['warnings'])
        self.assertIn('positive_discount_amount',bad['warnings'])
        self.assertIn('item_sum_mismatch',bad['warnings'])

    def test_quicklook_can_split_inside_word_and_money_without_losing_any_token(self):
        from receiptbot.parsers.dm import quicklook_segments_match
        text,expected=self.column_fixture()
        table=expected['quicklook_segments'][1]
        a=table.index('Andere')+3
        b=table.index('4,00')+1
        parts=[expected['quicklook_segments'][0],table[:a],table[a:b],table[b:],expected['quicklook_segments'][2]]
        self.assertTrue(quicklook_segments_match(parts,text))
        expected.update(text='\n'.join(parts),quicklook_segments=parts)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bon.pdf';pdf(p,text)
            self.assertEqual(validate_receipt(p,expected)['original_format'],'pdf')

    def test_rejoining_chunks_cannot_hide_changed_amount_or_missing_tax_marker(self):
        from receiptbot.parsers.dm import quicklook_segments_match
        text,expected=self.column_fixture();table=expected['quicklook_segments'][1]
        a=table.index('Andere')+3;b=table.index('4,00')+1
        for changed in (table.replace('1,00','1,01'),table.replace('§1','1')):
            parts=[expected['quicklook_segments'][0],changed[:a],changed[a:b],changed[b:],expected['quicklook_segments'][2]]
            self.assertFalse(quicklook_segments_match(parts,text))

    def test_known_dm_original_uses_observed_list_date_and_requires_exact_printed_fiscal_identity(self):
        from unittest.mock import patch,MagicMock
        from receiptbot.workflow import Exports
        from receiptbot.archive import file_digest
        parts=[TEXT.splitlines()[1],TEXT[TEXT.index('SN-Kasse:'):]]
        expected=dict(merchant='dm',date='2026-02-01',total_cents=500,text='\n'.join(parts),quicklook_segments=parts)
        self.assertIsNone(parse_text(expected['text'],'dm')['date'])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inbox=root/'incoming';inbox.mkdir()
            store=Exports(root/'data',root/'output');job=store.prepare(expected,inbox)
            source=pdf(inbox/'bon.pdf',TEXT)
            with patch('receiptbot.workflow.wait_for_file',return_value=(source,*file_digest(source))):store.finish(job)
            self.assertIsNotNone(store.known_ui_original(expected))
            self.assertIsNone(store.known_ui_original(dict(expected,date='2026-02-02')))
            self.assertIsNone(store.known_ui_original(dict(expected,text=expected['text'].replace('123456','999999'))))

    def make_preview_adapter(self, previews):
        from unittest.mock import MagicMock
        from receiptbot.adapters.dm import Dm
        adapter=Dm(MagicMock());adapter.tap=MagicMock();adapter.close_receipt=MagicMock()
        adapter.wait=MagicMock(side_effect=[v for parts in previews for v in (True,parts)])
        return adapter

    def test_printed_total_handles_split_amount_and_excludes_subtotal(self):
        from receiptbot.parsers.dm import quicklook_total
        self.assertEqual(quicklook_total(['Zwischensumme EUR 7,00\nSUM','ME EUR 5,','00']),500)
        for parts in (['No total'],['SUMME EUR 5,00\nSUMME EUR 6,00']):
            with self.assertRaises(ValueError):quicklook_total(parts)

    def test_list_total_discrepancy_requires_two_stable_ui_selections_before_export(self):
        from receiptbot.adapters.dm import Entry
        parts=TEXT.splitlines();adapter=self.make_preview_adapter([parts,parts])
        expected=adapter.open_receipt(Entry('SYNTHETIC link','2026-02-01',700))
        self.assertEqual(expected['total_cents'],500)
        self.assertEqual(expected['list_total_cents'],700)
        self.assertTrue(expected['list_total_mismatch'])
        self.assertEqual(expected['ui_total_source'],'quicklook_summe_confirmed_twice')
        self.assertEqual(adapter.close_receipt.call_count,1)
        self.assertEqual(adapter.tap.call_count,4)

    def test_list_total_discrepancy_never_accepts_changing_fiscal_identity(self):
        from receiptbot.adapters.dm import Entry
        first=TEXT.splitlines();second=TEXT.replace('TA-Nummer: 123456','TA-Nummer: 999999').splitlines()
        adapter=self.make_preview_adapter([first,second])
        with self.assertRaisesRegex(ValueError,'ändert'):adapter.open_receipt(Entry('SYNTHETIC','2026-02-01',700))

    def test_normal_list_total_needs_no_reselection(self):
        from receiptbot.adapters.dm import Entry
        adapter=self.make_preview_adapter([TEXT.splitlines()])
        expected=adapter.open_receipt(Entry('SYNTHETIC','2026-02-01',500))
        self.assertEqual(expected['total_cents'],500)
        adapter.close_receipt.assert_not_called()

    def test_confirmed_list_mismatch_preserves_pdf_total_and_review_flag_in_reports(self):
        import csv,json
        from unittest.mock import patch
        from receiptbot.workflow import Exports
        from receiptbot.reporting import report
        from receiptbot.archive import file_digest
        parts=TEXT.splitlines();expected=dict(merchant='dm',date='2026-02-01',total_cents=500,text='\n'.join(parts),quicklook_segments=parts,
            list_total_cents=700,list_total_mismatch=True,ui_total_source='quicklook_summe_confirmed_twice')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);incoming=root/'incoming';incoming.mkdir()
            store=Exports(root/'data',root/'output');job=store.prepare(expected,incoming);source=pdf(incoming/'bon.pdf',TEXT)
            with patch('receiptbot.workflow.wait_for_file',return_value=(source,*file_digest(source))):store.finish(job)
            report(root/'data',root/'output')
            with (root/'output/reports/receipts.csv').open() as f:row=next(csv.DictReader(f))
            self.assertEqual(row['total_cents'],'500');self.assertEqual(row['list_total_cents'],'700')
            self.assertEqual(row['status'],'review_required')
            self.assertIn('app_list_total_mismatch',row['warnings'])
            self.assertEqual(file_digest(source),file_digest(next((root/'output/originals').rglob('*.pdf'))))

    def test_unconfirmed_mismatch_or_changed_printed_total_is_rejected(self):
        expected=dict(merchant='dm',date='2026-02-01',total_cents=500,text=TEXT,quicklook_segments=TEXT.splitlines(),
            list_total_cents=700,list_total_mismatch=True,ui_total_source='quicklook_summe')
        with tempfile.TemporaryDirectory() as directory:
            source=pdf(Path(directory)/'bon.pdf',TEXT)
            with self.assertRaises(ValueError):validate_receipt(source,expected)
            changed=dict(expected,text=TEXT.replace('SUMME EUR 5,00','SUMME EUR 5,01'),quicklook_segments=TEXT.replace('SUMME EUR 5,00','SUMME EUR 5,01').splitlines(),ui_total_source='quicklook_summe_confirmed_twice')
            with self.assertRaises(ValueError):validate_receipt(source,changed)

    def test_pdfkit_invisible_amount_is_read_only_inside_selected_document(self):
        from receiptbot.parsers.dm import quicklook_total
        from html import escape
        fields=['SUMME EUR','5,00',TEXT[TEXT.index('SN-Kasse:'):]]
        nodes=''.join('<Node type="XCUIElementTypeStaticText" visible="'+('false' if i==1 else 'true')+'" label="'+escape(v,quote=True).replace('\n','&#10;')+'"/>' for i,v in enumerate(fields))
        xml='<App><Node type="XCUIElementTypeStaticText" visible="false" label="OUTSIDE DOCUMENT SUMME EUR 99,00"/><Node name="QLPDFViewControllerViewAccessibilityIdentifier">'+nodes+'</Node></App>'
        parts=quicklook_segments(xml)
        self.assertEqual(quicklook_total(parts),500)
        self.assertFalse(any('OUTSIDE DOCUMENT' in p for p in parts))

    def test_receipt_links_behind_header_or_bottom_navigation_are_not_tapped(self):
        label='Im Markt eingekauft, Am 01.02.2026, 5,00 €'
        def link(y):return '<Node type="XCUIElementTypeLink" visible="true" y="'+str(y)+'" height="99" label="'+escape(label,quote=True)+'"/>'
        chrome='<Node type="XCUIElementTypeButton" visible="true" name="BackButton" y="62" height="44"/><Node type="XCUIElementTypeButton" visible="true" name="Mein Konto" y="795" height="54"/>'
        self.assertEqual(list_entries('<App>'+chrome+link(48)+'</App>'),[])
        self.assertEqual(list_entries('<App>'+chrome+link(750)+'</App>'),[])
        self.assertEqual(len(list_entries('<App>'+chrome+link(200)+'</App>')),1)

    def test_dm_does_not_scroll_an_unexpected_tab(self):
        from receiptbot.adapters.dm import Dm
        adapter=Dm(MagicMock());adapter.source=MagicMock(return_value='<App><Node name="Mein Konto" visible="true"/></App>')
        with self.assertRaisesRegex(ValueError,'Einkaufsliste'):adapter.scroll()
        adapter.driver.execute_script.assert_not_called()
