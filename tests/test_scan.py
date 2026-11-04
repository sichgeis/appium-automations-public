from contextlib import nullcontext, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from receiptbot.workflow import export_receipts
from receiptbot.share_sheet import ShareSheetController


class ScanTests(unittest.TestCase):
    def test_repeated_list_stops_after_two_bounded_scrolls(self):
        config = {'server_url': 'http://127.0.0.1:4723', 'udid': 'synthetic',
                  'apps': {'kaufland': {'bundle_id': 'synthetic.kaufland'}}}
        adapter = MagicMock()
        adapter.entries.return_value = []
        with tempfile.TemporaryDirectory() as directory, patch('receiptbot.session.ROOT', Path(directory)), \
             patch('receiptbot.session.session', return_value=nullcontext()), \
             patch('receiptbot.server.local_server', return_value=nullcontext()), \
             patch('receiptbot.adapters.adapter_for', return_value=adapter), \
             patch('receiptbot.workflow.mac_name', return_value='synthetic-mac'), redirect_stdout(io.StringIO()):
            self.assertEqual(export_receipts(config, 'kaufland'), 0)
        self.assertEqual(adapter.scroll.call_count, 2)

    def test_large_run_cannot_skip_three_original_proof(self):
        config = {'server_url': 'http://127.0.0.1:4723', 'udid': 'synthetic',
                  'apps': {'kaufland': {'bundle_id': 'synthetic.kaufland'}}}
        with tempfile.TemporaryDirectory() as directory, patch('receiptbot.session.ROOT', Path(directory)), \
             patch('receiptbot.session.session') as connect:
            with self.assertRaisesRegex(ValueError, 'drei'):
                export_receipts(config, 'kaufland', all_receipts=True, approve_large=True)
            connect.assert_not_called()

    def test_airdrop_recipient_is_exact_and_ambiguous_target_never_clicked(self):
        ui = MagicMock()
        ui.driver.find_elements.return_value = [object(), object()]
        controller = ShareSheetController(ui)
        with self.assertRaises(ValueError):
            controller.send('synthetic-mac')
        ui.tap.assert_not_called()
        ui.driver.find_elements.return_value = [object()]
        controller.send('synthetic-mac')
        using, predicate = ui.tap.call_args.args
        self.assertIn('name == "airDropCell"', predicate)
        self.assertIn('label == "synthetic-mac"', predicate)

    def test_same_list_metadata_different_receipt_text_never_skipped(self):
        config = {'server_url': 'http://127.0.0.1:4723', 'udid': 'synthetic',
                  'apps': {'kaufland': {'bundle_id': 'synthetic.kaufland'}}}
        adapter = MagicMock()
        # Getrennte Seiten mit gleichem Datum/Betrag/Anzahl, aber verschiedenem Inhalt.
        adapter.entries.side_effect = [[object()], [object()]]
        adapter.open_receipt.side_effect = [dict(text='SYNTHETIC receipt A'), dict(text='SYNTHETIC receipt B')]
        store = MagicMock()
        store.pending.return_value = None
        store.finish.side_effect = [{'already_stored':False,'path':Path('/synthetic/a.pdf')}, {'already_stored':False,'path':Path('/synthetic/b.pdf')}]
        with tempfile.TemporaryDirectory() as directory, patch('receiptbot.session.ROOT', Path(directory)), \
             patch('receiptbot.workflow.Exports', return_value=store), \
             patch('receiptbot.session.session', return_value=nullcontext()), \
             patch('receiptbot.server.local_server', return_value=nullcontext()), \
             patch('receiptbot.adapters.adapter_for', return_value=adapter), \
             patch('receiptbot.share_sheet.ShareSheetController'), \
             patch('receiptbot.workflow.mac_name', return_value='synthetic-mac'), redirect_stdout(io.StringIO()):
            self.assertEqual(export_receipts(config, 'kaufland', limit=2), 0)
        self.assertEqual(adapter.send_to_mac.call_count, 2)
        self.assertEqual(adapter.close_receipt.call_count, 2)

    def run_synthetic_scan(self, receipts, originals, limit):
        config={'server_url':'http://127.0.0.1:4723','udid':'synthetic','apps':{'kaufland':{'bundle_id':'synthetic.kaufland'}}}
        adapter=MagicMock();adapter.entries.side_effect=[[object()] for _ in receipts]
        adapter.open_receipt.side_effect=receipts
        store=MagicMock();store.pending.return_value=None
        store.finish.side_effect=[dict(already_stored=False,path=Path('/synthetic')/name) for name in originals]
        with tempfile.TemporaryDirectory() as directory, patch('receiptbot.session.ROOT',Path(directory)), \
             patch('receiptbot.workflow.Exports',return_value=store), \
             patch('receiptbot.session.session',return_value=nullcontext()), \
             patch('receiptbot.server.local_server',return_value=nullcontext()), \
             patch('receiptbot.adapters.adapter_for',return_value=adapter), \
             patch('receiptbot.share_sheet.ShareSheetController'), \
             patch('receiptbot.workflow.mac_name',return_value='synthetic-mac'), redirect_stdout(io.StringIO()):
            self.assertEqual(export_receipts(config,'kaufland',limit=limit,max_pages=len(receipts)),0)
        return adapter,store

    def test_identical_ui_without_identity_is_verified_again_and_end_is_still_bounded(self):
        receipt=dict(date='2026-10-30',total_cents=100,text='SYNTHETIC same basket',ui_identity_unavailable=True)
        adapter,store=self.run_synthetic_scan([receipt]*4,['a.pdf','b.pdf','b.pdf','b.pdf'],3)
        self.assertEqual(store.finish.call_count,4)
        self.assertEqual(adapter.scroll.call_count,3)
        self.assertEqual(adapter.close_receipt.call_count,4)

    def test_same_dateless_ui_on_different_observed_dates_is_not_skipped(self):
        receipts=[dict(date=day,total_cents=100,text='SYNTHETIC same basket') for day in ('2026-10-30','2026-10-29')]
        adapter,store=self.run_synthetic_scan(receipts,['a.pdf','b.pdf'],2)
        self.assertEqual(store.finish.call_count,2)

    def test_limit_counts_different_verified_originals_not_repeated_weak_previews(self):
        receipt=dict(date='2026-10-30',total_cents=100,text='SYNTHETIC same basket',ui_identity_unavailable=True)
        adapter,store=self.run_synthetic_scan([receipt]*3,['a.pdf','a.pdf','b.pdf'],2)
        self.assertEqual(store.finish.call_count,3)
        self.assertEqual(adapter.close_receipt.call_count,3)

    def test_new_only_crosses_known_pages_before_exporting_new_receipt(self):
        config={'server_url':'http://127.0.0.1:4723','udid':'synthetic','apps':{'kaufland':{'bundle_id':'synthetic.kaufland'}}}
        adapter=MagicMock();adapter.entries.side_effect=[[object()]]*4
        adapter.open_receipt.side_effect=[dict(text='SYNTHETIC '+name) for name in ('A','B','C','D')]
        store=MagicMock();store.pending.return_value=None
        store.known_ui_original.side_effect=[dict(path='/synthetic/'+name) for name in ('A','B','C')]+[None]
        store.finish.return_value=dict(path='/synthetic/D',already_stored=False)
        with tempfile.TemporaryDirectory() as directory, patch('receiptbot.session.ROOT',Path(directory)), \
             patch('receiptbot.workflow.Exports',return_value=store), \
             patch('receiptbot.session.session',return_value=nullcontext()), \
             patch('receiptbot.server.local_server',return_value=nullcontext()), \
             patch('receiptbot.adapters.adapter_for',return_value=adapter), \
             patch('receiptbot.share_sheet.ShareSheetController'), \
             patch('receiptbot.workflow.mac_name',return_value='synthetic-mac'), redirect_stdout(io.StringIO()):
            self.assertEqual(export_receipts(config,'kaufland',new_only=True,limit=1),0)
        self.assertEqual(store.finish.call_count,1)
        self.assertEqual(adapter.share.call_count,1)
        self.assertEqual(adapter.scroll.call_count,3)
        self.assertEqual(adapter.close_receipt.call_count,4)

    def test_all_starts_at_list_top_and_explicit_resume_preserves_current_position(self):
        config={'server_url':'http://127.0.0.1:4723','udid':'synthetic','apps':{'kaufland':{'bundle_id':'synthetic.kaufland'}}}
        for resume in (False,True):
            adapter=MagicMock();adapter.entries.return_value=[]
            store=MagicMock();store.pending.return_value=None;store.verified_count.return_value=3
            with tempfile.TemporaryDirectory() as directory, patch('receiptbot.session.ROOT',Path(directory)), \
                 patch('receiptbot.workflow.Exports',return_value=store), \
                 patch('receiptbot.session.session',return_value=nullcontext()), \
                 patch('receiptbot.server.local_server',return_value=nullcontext()), \
                 patch('receiptbot.adapters.adapter_for',return_value=adapter), \
                 patch('receiptbot.workflow.mac_name',return_value='synthetic-mac'), redirect_stdout(io.StringIO()):
                self.assertEqual(export_receipts(config,'kaufland',all_receipts=True,approve_large=True,resume_list=resume),0)
            self.assertEqual(adapter.rewind_list.call_count,0 if resume else 1)

    def test_resume_position_requires_all_before_connecting_device(self):
        with patch('receiptbot.session.session') as connect:
            with self.assertRaisesRegex(ValueError,'--all'):export_receipts({},'kaufland',resume_list=True)
            connect.assert_not_called()

    def run_since_scan(self, entries, receipts, since='2026-06-01'):
        config={'server_url':'http://127.0.0.1:4723','udid':'synthetic','apps':{'dm':{'bundle_id':'synthetic.dm'}}}
        adapter=MagicMock();adapter.entries.side_effect=entries;adapter.open_receipt.side_effect=receipts
        store=MagicMock();store.pending.return_value=None
        store.finish.return_value=dict(path='/synthetic/new.pdf',already_stored=False)
        with tempfile.TemporaryDirectory() as directory,patch('receiptbot.session.ROOT',Path(directory)), \
             patch('receiptbot.workflow.Exports',return_value=store),patch('receiptbot.session.session',return_value=nullcontext()), \
             patch('receiptbot.server.local_server',return_value=nullcontext()),patch('receiptbot.adapters.adapter_for',return_value=adapter), \
             patch('receiptbot.share_sheet.ShareSheetController'),patch('receiptbot.workflow.mac_name',return_value='synthetic-mac'),redirect_stdout(io.StringIO()):
            self.assertEqual(export_receipts(config,'dm',limit=1,since=since,max_pages=len(entries)),0)
        return adapter,store

    def test_since_is_inclusive_and_does_not_even_open_explicitly_older_entries(self):
        from types import SimpleNamespace
        old=SimpleNamespace(date='2026-05-31');included=SimpleNamespace(date='2026-06-01')
        adapter,store=self.run_since_scan([[old,included]],[dict(date='2026-06-01',text='SYNTHETIC included')])
        adapter.open_receipt.assert_called_once_with(included)
        self.assertEqual(store.prepare.call_count,1)
        self.assertEqual(adapter.rewind_list.call_count,1)

    def test_since_never_invents_year_for_undated_list_and_closes_old_receipt_without_export(self):
        from types import SimpleNamespace
        adapter,store=self.run_since_scan([[SimpleNamespace(day=31),SimpleNamespace(day=1)]],
            [dict(date='2026-05-31',text='SYNTHETIC old'),dict(date='2026-06-01',text='SYNTHETIC included')])
        self.assertEqual(adapter.open_receipt.call_count,2)
        self.assertEqual(adapter.close_receipt.call_count,2)
        self.assertEqual(adapter.share.call_count,1)
        self.assertEqual(store.prepare.call_args.args[0]['date'],'2026-06-01')

    def test_old_pages_do_not_prematurely_end_scan_before_later_in_range_entry(self):
        from types import SimpleNamespace
        pages=[[SimpleNamespace(date=day)] for day in ('2026-05-29','2026-05-28','2026-06-01')]
        adapter,store=self.run_since_scan(pages,[dict(date='2026-06-01',text='SYNTHETIC included')])
        self.assertEqual(adapter.scroll.call_count,2)
        self.assertEqual(adapter.open_receipt.call_count,1)
        self.assertEqual(store.finish.call_count,1)

    def test_invalid_since_stops_before_device_connection(self):
        with patch('receiptbot.session.session') as connect:
            with self.assertRaises(ValueError):export_receipts({},'dm',since='2026-06-99')
            connect.assert_not_called()

    def test_pending_older_receipt_is_not_archived_under_new_since_scope(self):
        import json
        config={'server_url':'http://127.0.0.1:4723','udid':'synthetic','apps':{'dm':{'bundle_id':'synthetic.dm'}}}
        store=MagicMock();store.pending.return_value={'expected':json.dumps(dict(date='2026-05-31'))}
        with tempfile.TemporaryDirectory() as directory,patch('receiptbot.session.ROOT',Path(directory)), \
             patch('receiptbot.workflow.Exports',return_value=store),patch('receiptbot.session.session') as connect:
            with self.assertRaisesRegex(ValueError,'Datumsuntergrenze'):export_receipts(config,'dm',since='2026-06-01')
        store.finish.assert_not_called();connect.assert_not_called()
