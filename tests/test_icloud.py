from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from receiptbot.icloud import transport_settings
from receiptbot.share_sheet import picker_matches, ShareSheetController
from receiptbot.transport import snapshot, wait_for_file
from receiptbot.workflow import Exports
from receiptbot.archive import file_digest
from synthetic import TEXT, pdf


def picker(folder='appium-share', cloud=True):
    return ('<App><XCUIElementTypeNavigationBar name="FullDocumentManagerViewControllerNavigationBar" visible="true">'
            '<XCUIElementTypeButton name="' + folder + '" visible="true"/>'
            '<XCUIElementTypeButton name="Save" visible="true"/>'
            '</XCUIElementTypeNavigationBar>'
            + ('<XCUIElementTypeStaticText label="Synced with iCloud" visible="true"/>' if cloud else '') + '</App>')


class ICloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = self.root / 'appium-share'
        self.directory.mkdir()
        self.expected = dict(merchant='kaufland', date='2026-10-30', total_cents=380, text=TEXT)

    def test_explicit_destination_configuration_and_picker_guards(self):
        config = {'transport': {'kind':'icloud', 'directory':str(self.directory), 'folder_name':'appium-share'}}
        self.assertEqual(transport_settings(config), ('icloud', self.directory.resolve(), 'appium-share'))
        config['transport']['folder_name'] = 'different'
        with self.assertRaises(ValueError):
            transport_settings(config)
        self.assertTrue(picker_matches(picker(), 'appium-share'))
        self.assertFalse(picker_matches(picker('another-folder'), 'appium-share'))
        self.assertFalse(picker_matches(picker(cloud=False), 'appium-share'))

    def test_exact_uuid_ignores_other_downloads_and_never_accepts_old_file(self):
        baseline = snapshot(self.directory)
        name = 'appium-' + 'a'*32 + '.pdf'
        path = pdf(self.directory / name)
        pdf(self.directory / 'unrelated.pdf')
        with patch('receiptbot.icloud.is_placeholder', return_value=False):
            candidate, size, digest = wait_for_file(self.directory, baseline, timeout=1, stable_seconds=0, expected_name=name)
        self.assertEqual(candidate, path)
        self.assertEqual((size, digest), file_digest(path))
        with self.assertRaisesRegex(ValueError, 'bereits'):
            wait_for_file(self.directory, snapshot(self.directory), expected_name=name)
        with self.assertRaises(ValueError):
            wait_for_file(self.directory, {}, expected_name='../elsewhere.pdf')

    def test_placeholder_triggers_download_but_is_not_success(self):
        baseline = snapshot(self.directory)
        name = 'appium-' + 'b'*32 + '.pdf'
        pdf(self.directory / name)
        with patch('receiptbot.icloud.is_placeholder', return_value=True), \
             patch('receiptbot.icloud.request_download') as request, \
             patch('receiptbot.transport.file_digest') as digest:
            with self.assertRaises(ValueError):
                wait_for_file(self.directory, baseline, timeout=.3, stable_seconds=0, expected_name=name, hydrate=True)
            request.assert_called_once()
            digest.assert_not_called()

    def test_save_name_and_destination_must_both_be_confirmed(self):
        ui = MagicMock()
        ui.source.return_value = picker()
        field = MagicMock()
        field.is_displayed.return_value = True
        name = 'appium-' + 'c'*32 + '.pdf'
        field.get_attribute.side_effect = ['20261031_165646', name]
        ui.driver.find_elements.return_value = [field]
        controller = ShareSheetController(ui)
        controller.save_file('appium-share', name)
        field.clear.assert_called_once()
        field.send_keys.assert_called_once_with(name[:-4])
        ui.tap.assert_called_once_with('accessibility id', 'DOCPicker.actionButton')
        with self.assertRaises(ValueError):
            controller.save_file('another-folder', name)
        with self.assertRaises(ValueError):
            controller.save_file('appium-share', 'existing.pdf')

    def test_manual_import_proves_bytes_but_retains_manual_provenance(self):
        store = Exports(self.root / 'data', self.root / 'output')
        source = pdf(self.directory / 'manual.pdf')
        result = store.adopt_received(self.expected, source)
        self.assertTrue(result['origin_verified'])
        self.assertEqual(source.read_bytes(), result['path'].read_bytes())
        with closing(store.connect()) as db:
            row = db.execute('SELECT * FROM transfers').fetchone()
            self.assertEqual(row['state'], 'verified')
            self.assertEqual(json.loads(row['expected'])['transport_kind'], 'icloud-manual')
        self.assertTrue(store.adopt_received(self.expected, source)['already_stored'])

    def test_icloud_resume_uses_persisted_exact_name(self):
        store = Exports(self.root / 'data', self.root / 'output')
        name = 'appium-' + 'd'*32 + '.pdf'
        identifier = store.prepare(dict(self.expected, transport_kind='icloud', transfer_name=name), self.directory)
        source = pdf(self.directory / name)
        with patch('receiptbot.workflow.wait_for_file', return_value=(source, *file_digest(source))) as wait:
            store.finish(identifier)
        self.assertEqual(wait.call_args.kwargs, dict(expected_name=name, hydrate=True))

    def test_collision_is_rejected_before_saving(self):
        store = Exports(self.root / 'data', self.root / 'output')
        name = 'appium-' + 'e'*32 + '.pdf'
        pdf(self.directory / name)
        with self.assertRaisesRegex(ValueError, 'existiert bereits'):
            store.prepare(dict(self.expected, transport_kind='icloud', transfer_name=name), self.directory)
        self.assertIsNone(store.pending('kaufland'))

    def test_observed_folder_actions_menu_title_is_exact(self):
        actions = picker().replace('name="appium-share"', 'name="appium-share, Actions Menu"')
        self.assertTrue(picker_matches(actions, 'appium-share'))
        self.assertFalse(picker_matches(actions.replace('appium-share,', 'appium-share-other,'), 'appium-share'))

    def test_save_uses_only_observed_filename_field_not_other_text_fields(self):
        ui = MagicMock()
        ui.source.return_value = picker()
        filename = 'appium-' + 'f'*32 + '.pdf'
        target, unrelated = MagicMock(), MagicMock()
        target.is_displayed.return_value = True
        target.get_attribute.side_effect = ['20261031_165646', filename]
        def find(using, name):
            if using == 'accessibility id' and name == 'DOCPicker.filenameTextField':
                return [target]
            return [target, unrelated]
        ui.driver.find_elements.side_effect = find
        controller = ShareSheetController(ui)
        with patch.object(controller, 'tap_unique_label'):
            controller.save_file('appium-share', filename)
        target.clear.assert_called_once()
        unrelated.clear.assert_not_called()
        unrelated.send_keys.assert_not_called()

    def test_observed_provider_confirms_icloud_when_keyboard_hides_sync_footer(self):
        xml = picker(cloud=False).replace('</App>', '<XCUIElementTypeOther visible="true" name="DOC.browsingRoot Source: com.apple.CloudDocs.iCloudDriveFileProvider/SYNTHETIC, Title: appium-share"/></App>')
        self.assertTrue(picker_matches(xml, 'appium-share'))
        self.assertTrue(picker_matches(xml.replace('Title: appium-share','Title: iCloud Drive'), 'appium-share'))
        self.assertFalse(picker_matches(xml.replace('com.apple.CloudDocs.iCloudDriveFileProvider','synthetic.otherProvider'), 'appium-share'))

    def test_matching_folder_entry_in_wrong_directory_is_not_a_target_confirmation(self):
        xml = picker('other-folder').replace('</App>', '<XCUIElementTypeButton name="appium-share" visible="true"/></App>')
        self.assertFalse(picker_matches(xml, 'appium-share'))

    def test_prepared_exact_job_name_can_be_finished_without_retyping(self):
        ui = MagicMock()
        ui.source.return_value = picker()
        name = 'appium-' + 'a'*32 + '.pdf'
        field = MagicMock()
        field.is_displayed.return_value = True
        field.get_attribute.return_value = name[:-4]
        ui.driver.find_elements.return_value = [field]
        controller = ShareSheetController(ui)
        controller.save_file('appium-share', name)
        field.clear.assert_not_called()
        field.send_keys.assert_not_called()
        ui.tap.assert_called_once_with('accessibility id', 'DOCPicker.actionButton')

    def test_observed_german_png_picker_preserves_actual_original_format(self):
        ui = MagicMock()
        xml = picker().replace('name="Save"','name="DOCPicker.actionButton" label="Sichern"')
        self.assertTrue(picker_matches(xml, 'appium-share'))
        ui.source.return_value = xml
        name = 'appium-' + 'b'*32 + '.png'
        field = MagicMock()
        field.is_displayed.return_value = True
        field.get_attribute.side_effect = ['PNG-Bild', name[:-4]]
        ui.driver.find_elements.return_value = [field]
        ShareSheetController(ui).save_file('appium-share', name, r'PNG-Bild(?:\.png)?')
        field.send_keys.assert_called_once_with(name[:-4])
        ui.tap.assert_called_once_with('accessibility id', 'DOCPicker.actionButton')
