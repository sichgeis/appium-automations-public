import unittest
from unittest.mock import MagicMock, PropertyMock
from selenium.common.exceptions import NoAlertPresentException
from receiptbot.ui import NativeUI


class NativeUiTests(unittest.TestCase):
    def driver(self):
        driver = MagicMock()
        driver.is_locked.return_value = False
        driver.page_source = '<App/>'
        type(driver.switch_to).alert = PropertyMock(side_effect=NoAlertPresentException)
        return driver

    def test_lock_stops_before_any_ui_or_alert_access(self):
        driver = self.driver()
        driver.is_locked.return_value = True
        with self.assertRaisesRegex(ValueError, 'gesperrt'):
            NativeUI(driver).source()
        driver.find_elements.assert_not_called()

    def test_system_permission_stops_even_if_missing_from_app_xml(self):
        driver = self.driver()
        type(driver.switch_to).alert = PropertyMock(return_value=object())
        with self.assertRaisesRegex(ValueError, 'Systemdialog'):
            NativeUI(driver).source()
        driver.find_element.assert_not_called()

    def test_no_alert_does_not_block_and_hidden_app_alert_is_ignored(self):
        driver = self.driver()
        driver.page_source = '<App><XCUIElementTypeAlert visible="false"/></App>'
        self.assertEqual(NativeUI(driver).source(), driver.page_source)
        driver.page_source = '<App><XCUIElementTypeAlert visible="true"/></App>'
        with self.assertRaisesRegex(ValueError, 'App-Dialog'):
            NativeUI(driver).source()
