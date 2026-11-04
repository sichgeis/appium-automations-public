import unittest
from receiptbot.adapters.kaufland import list_entries, xpath_literal


def listing(date='October.30.2026', amount='3,80 €'):
    return ('<App><XCUIElementTypeOther>'
        '<XCUIElementTypeButton name="dateLabel" label="' + date + '" visible="true"/>'
        '<XCUIElementTypeButton name="productsLabel" label="3 items"/>'
        '<XCUIElementTypeButton name="totalLabel" label="' + amount + '"/>'
        '</XCUIElementTypeOther></App>')


class NavigationTests(unittest.TestCase):
    def test_observed_sibling_structure_and_date(self):
        entry, = list_entries(listing())
        self.assertEqual(entry.day, '2026-10-30')
        self.assertEqual(entry.amount, 380)
        self.assertEqual(len(entry.key), 64)

    def test_ambiguous_entries_stop_instead_of_losing_receipts(self):
        xml = listing().replace('</App>', listing().removeprefix('<App>'))
        with self.assertRaisesRegex(ValueError, 'nicht eindeutig'):
            list_entries(xml)

    def test_changed_ui_stops_and_xpath_values_are_quoted(self):
        with self.assertRaises(ValueError):
            list_entries(listing().replace('productsLabel', 'unknownLabel'))
        with self.assertRaises(ValueError):
            list_entries(listing(date='unrecognized'))
        self.assertEqual(xpath_literal('plain'), '"plain"')
        self.assertTrue(xpath_literal('both\'"quotes').startswith('concat('))

    def open_synthetic_receipt(self, text):
        from unittest.mock import MagicMock
        from html import escape
        from receiptbot.adapters.kaufland import Kaufland
        entry, = list_entries(listing())
        adapter = Kaufland(MagicMock())
        adapter.tap = MagicMock()
        adapter.wait = MagicMock(return_value='<App><XCUIElementTypeStaticText type="XCUIElementTypeStaticText" label="'+escape(text,quote=True).replace('\n','&#10;')+'"/></App>')
        return adapter.open_receipt(entry)

    def dateless_body(self):
        return 'Kaufland - Synthetische Filiale\nPreis EUR\nTestartikel '+('Beschreibung '*20)+'3,80 B\nSumme 3,80\n'

    def test_missing_ui_date_still_requires_real_pdf_date(self):
        import tempfile
        from pathlib import Path
        from synthetic import pdf
        from receiptbot.parsing import validate_receipt
        body = self.dateless_body()
        expected = self.open_synthetic_receipt(body)
        self.assertTrue(expected['ui_date_missing'])
        self.assertTrue(expected['ui_identity_unavailable'])
        self.assertEqual(expected['date'],'2026-10-30')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'bon.pdf'
            pdf(target,body+'Datum: 30.10.26 Zeit: 12:34:00 Bon: 1000\n')
            self.assertEqual(validate_receipt(target,expected)['date'],'2026-10-30')
            for text in (body,body+'Datum: 29.10.26 Zeit: 12:34:00 Bon: 1000\n'):
                pdf(target,text)
                with self.assertRaises(ValueError):validate_receipt(target,expected)

    def test_printed_wrong_or_ambiguous_ui_dates_still_stop(self):
        for dates in ('29.10.2026','30.10.2026 29.10.2026'):
            with self.assertRaises(ValueError):self.open_synthetic_receipt(self.dateless_body()+dates)

    def test_missing_ui_date_never_bypasses_amount_check(self):
        with self.assertRaises(ValueError):self.open_synthetic_receipt(self.dateless_body().replace('Summe 3,80','Summe 3,81'))

    def test_unrecognized_explicit_date_field_is_not_treated_as_absent(self):
        with self.assertRaises(ValueError):self.open_synthetic_receipt(self.dateless_body()+'Datum: UNKNOWN')

    def test_full_printed_receipt_identity_allows_safe_in_run_overlap_check(self):
        text=self.dateless_body()+'Datum: 30.10.26 Zeit: 12:34:00 Bon: 1000\nFiliale: 1000 Kasse: 1\n'
        expected=self.open_synthetic_receipt(text)
        self.assertFalse(expected['ui_identity_unavailable'])

    def test_full_list_rewinds_to_stable_top_with_bounded_upward_scrolls(self):
        from unittest.mock import MagicMock
        from receiptbot.adapters.kaufland import Kaufland
        adapter=Kaufland(MagicMock())
        lower=MagicMock(key='lower');top=MagicMock(key='top')
        adapter.entries=MagicMock(side_effect=[[lower],[top],[top],[top]])
        adapter.scroll=MagicMock()
        adapter.rewind_list(max_steps=4)
        self.assertEqual(adapter.scroll.call_count,3)
        self.assertTrue(all(call.args==('up',) for call in adapter.scroll.call_args_list))

    def test_rewind_stops_if_top_never_stabilizes(self):
        from unittest.mock import MagicMock
        from receiptbot.adapters.kaufland import Kaufland
        adapter=Kaufland(MagicMock())
        adapter.entries=MagicMock(side_effect=[[MagicMock(key=str(i))] for i in range(3)])
        adapter.scroll=MagicMock()
        with self.assertRaises(ValueError):adapter.rewind_list(max_steps=3)
        self.assertEqual(adapter.scroll.call_count,3)

    def test_temporarily_empty_kaufland_list_waits_for_loaded_entries(self):
        from unittest.mock import MagicMock,patch
        from receiptbot.adapters.kaufland import Kaufland
        adapter=Kaufland(MagicMock())
        adapter.source=MagicMock(side_effect=['<App/>',listing()])
        with patch('receiptbot.ui.time.sleep'):
            entries=adapter.entries()
        self.assertEqual(entries[0].day,'2026-10-30')
        self.assertEqual(adapter.source.call_count,2)

    def test_empty_list_timeout_is_not_silently_reported_as_list_end(self):
        from unittest.mock import MagicMock,patch
        from receiptbot.adapters.kaufland import Kaufland
        adapter=Kaufland(MagicMock());adapter.source=MagicMock(return_value='<App/>')
        with patch('receiptbot.ui.time.sleep'),patch('receiptbot.ui.time.monotonic',side_effect=[0,0,16]):
            with self.assertRaisesRegex(ValueError,'Kaufland-Bonliste'):adapter.entries()
