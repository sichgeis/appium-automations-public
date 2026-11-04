from contextlib import nullcontext, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from receiptbot.retailers import app_candidates, require_export_implementation
from receiptbot.discovery import apply_candidate, discover_apps


def payload(*apps):
    return {'result': {'apps': list(apps)}}


def app(name='Mein dm', bundle='synthetic.dm'):
    return {'name': name, 'bundleIdentifier': bundle, 'version': '1.0', 'irrelevant_private_field': 'SYNTHETIC_EXCLUDED'}


class RetailerTests(unittest.TestCase):
    def test_unimplemented_merchants_block_without_touching_driver(self):
        from receiptbot.adapters import adapter_for
        for merchant in ('unknown',):
            driver = MagicMock()
            with self.assertRaises(ValueError):
                adapter_for(merchant, driver)
            driver.assert_not_called()
            self.assertEqual(driver.mock_calls, [])
        require_export_implementation('kaufland')
        require_export_implementation('lidl')
        require_export_implementation('dm')
        require_export_implementation('rossmann')

    def test_matching_uses_real_metadata_only_and_excludes_unrelated_apps(self):
        result = app_candidates(payload(app(), app('Unrelated','synthetic.other')), 'dm')
        self.assertEqual(result, [{'name':'Mein dm','bundle_id':'synthetic.dm','version':'1.0'}])
        for merchant, name in (('lidl','Lidl Plus'), ('rossmann','ROSSMANN')):
            self.assertEqual(len(app_candidates(payload(app(name)), merchant)), 1)
        self.assertEqual(app_candidates(payload(app('RandomdmSuffix')), 'dm'), [])

    def test_unknown_shapes_and_conflicting_metadata_stop(self):
        for value in ({}, {'result':None}, payload(None), payload({'name':'dm'}),
                      payload(app(), dict(app(), version='2.0'))):
            with self.assertRaises(ValueError):
                app_candidates(value, 'dm')

    def test_multiple_lidl_apps_and_existing_configuration_never_silently_overwritten(self):
        candidates = app_candidates(payload(app('Lidl Plus','synthetic.plus'), app('Lidl','synthetic.shop')), 'lidl')
        config = {'udid':'SYNTHETIC', 'apps': {'lidl': {'bundle_id':'synthetic.original'}}}
        before = json.dumps(config)
        for choice in ([], candidates, candidates[:1]):
            with self.assertRaises(ValueError):
                apply_candidate(config, 'lidl', choice)
            self.assertEqual(json.dumps(config), before)

    def test_unique_candidate_preserves_other_private_config_and_does_not_enable_adapter(self):
        config = {'udid':'SYNTHETIC', 'apps': {'kaufland': {'bundle_id':'synthetic.kaufland'}}}
        apply_candidate(config, 'dm', app_candidates(payload(app()), 'dm'))
        self.assertEqual(config['udid'], 'SYNTHETIC')
        self.assertEqual(config['apps']['kaufland']['bundle_id'], 'synthetic.kaufland')
        self.assertEqual(config['apps']['dm']['bundle_id'], 'synthetic.dm')
        self.assertNotIn('adapter_implemented',config['apps']['dm'])

    def test_discovery_stores_only_selected_metadata_and_apply_is_explicit(self):
        config = {'udid':'SYNTHETIC', 'apps': {}}
        response = SimpleNamespace(returncode=0, stdout=json.dumps(payload(app(), app('Unrelated','synthetic.other'))))
        with tempfile.TemporaryDirectory() as directory, patch('receiptbot.discovery.ROOT', Path(directory)), \
             patch('receiptbot.discovery.device_lock', return_value=nullcontext()), \
             patch('receiptbot.discovery.load_config', return_value=config), \
             patch('receiptbot.discovery.device_status', return_value=(True,'ready')), \
             patch('receiptbot.discovery.subprocess.run', return_value=response) as command, redirect_stdout(io.StringIO()):
            path = Path(directory) / 'config.local.json'
            path.write_text(json.dumps(config))
            self.assertEqual(discover_apps('dm'), 0)
            self.assertNotIn('dm', json.loads(path.read_text())['apps'])
            stored = next((Path(directory) / 'data/app-discovery').glob('dm-*.json')).read_text()
            self.assertNotIn('synthetic.other', stored)
            self.assertNotIn('SYNTHETIC_EXCLUDED', stored)
            self.assertEqual(discover_apps('dm', apply=True), 0)
            self.assertEqual(json.loads(path.read_text())['apps']['dm']['bundle_id'], 'synthetic.dm')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('--include-all-apps', command.call_args.args[0])

    def test_offline_discovery_never_reads_apps_or_writes_config(self):
        with patch('receiptbot.discovery.load_config', return_value={'udid':'SYNTHETIC'}), \
             patch('receiptbot.discovery.device_lock', return_value=nullcontext()), \
             patch('receiptbot.discovery.device_status', return_value=(False,'connect phone')), \
             patch('receiptbot.discovery.subprocess.run') as command:
            with self.assertRaises(ValueError):
                discover_apps('dm')
            command.assert_not_called()
