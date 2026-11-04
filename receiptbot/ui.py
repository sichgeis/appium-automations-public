"""Gemeinsame native UI-Bedienung mit Sperr- und Systemdialogschutz."""
import time
import xml.etree.ElementTree as ET
from selenium.common.exceptions import NoAlertPresentException


class NativeUI:
    def __init__(self, driver):
        self.driver = driver

    def source(self):
        if self.driver.is_locked():
            raise ValueError('iPhone gesperrt. Selbst entsperren; Auto-Lock für den Lauf auf Nie setzen. Keine Klickwiederholung.')
        # iOS-Berechtigungen können in SpringBoard liegen und im App-XML fehlen.
        try:
            self.driver.switch_to.alert
        except NoAlertPresentException:
            pass
        else:
            raise ValueError('iOS-Systemdialog offen: angehalten, bitte selbst entscheiden. Keine automatische Zustimmung.')
        xml = self.driver.page_source
        if any(n.get('visible') == 'true' for n in ET.fromstring(xml).iter('XCUIElementTypeAlert')):
            raise ValueError('Unerwarteter App-Dialog: angehalten, bitte selbst prüfen.')
        return xml

    def wait(self, condition, timeout=15, description='Händler-/Speicheransicht'):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = condition(self.source())
            if value:
                return value
            time.sleep(.4)
        raise ValueError('Zeitlimit bei ' + description + '. Login, Navigation oder UI-Version prüfen.')

    def tap(self, using, value):
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        self.source()
        element = WebDriverWait(self.driver, 12).until(EC.element_to_be_clickable((using, value)))
        element.click()
        time.sleep(.6)

    def has(self, xml, name):
        return any(n.get('name') == name and n.get('visible') == 'true' for n in ET.fromstring(xml).iter())

    def rewind_list(self, max_steps=1000):
        previous = None
        unchanged = 0
        for _ in range(max_steps):
            entries = self.entries()
            if not entries:
                raise ValueError('Bonliste leer oder noch nicht geladen; Listenanfang nicht bestätigt.')
            current = tuple(getattr(entry,'key',repr(entry)) for entry in entries)
            unchanged = unchanged + 1 if current == previous else 0
            if unchanged >= 2:
                return
            previous = current
            self.scroll('up')
        raise ValueError('Listenanfang nach begrenztem Scrollen nicht bestätigt.')
