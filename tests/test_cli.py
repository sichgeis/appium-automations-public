from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
from receiptbot.__main__ import main


class CliTests(TestCase):
    def invoke(self, *args):
        with patch('sys.argv', ['receiptbot', *args]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main()

    def test_export_dry_run_never_connects_or_changes_files(self):
        with patch('receiptbot.workflow.export_receipts') as export, patch('receiptbot.__main__.load_config') as load:
            self.assertEqual(self.invoke('export', '--app', 'kaufland', '--dry-run'), 0)
            export.assert_not_called()
            load.assert_not_called()

    def test_large_run_without_explicit_approval_and_bad_limit_blocked(self):
        for args in [('--limit', '4'), ('--limit', '0'), ('--all',)]:
            with patch('receiptbot.workflow.export_receipts') as export:
                self.assertEqual(self.invoke('export', '--app', 'kaufland', *args), 2)
                export.assert_not_called()

    def test_empty_reports_are_honest_and_no_phone_required(self):
        with tempfile.TemporaryDirectory() as directory, patch('receiptbot.__main__.ROOT', Path(directory)):
            for command in ('parse', 'report'):
                self.assertEqual(self.invoke(command), 0)
            self.assertTrue((Path(directory) / 'output/reports/receipts.csv').is_file())

    def test_other_merchant_stops_before_session(self):
        from receiptbot.workflow import export_receipts
        from receiptbot.retailers import Retailer
        with patch.dict('receiptbot.retailers.RETAILERS', {'rossmann': Retailer('Rossmann', 'synthetic')}), patch('receiptbot.session.session') as connect:
            with self.assertRaisesRegex(ValueError, 'nicht implementiert'):
                export_receipts({}, 'rossmann')
            connect.assert_not_called()
