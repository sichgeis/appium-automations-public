"""Gemeinsame iOS-AirDrop-Zielprüfung, ausschließlich eigener Mac."""
import json
import re
import xml.etree.ElementTree as ET


class ShareSheetController:
    def __init__(self, ui):
        self.ui = ui

    def mac_selector(self, name):
        return ('type == "XCUIElementTypeCell" AND name == "airDropCell" AND label == '
                + json.dumps(name, ensure_ascii=False))

    def ensure_mac(self, name):
        self.ui.wait(lambda source: any(n.get('name') == 'airDropCell' and n.get('label') == name
                     and n.get('visible') == 'true' for n in ET.fromstring(source).iter()))
        if len(self.ui.driver.find_elements('-ios predicate string', self.mac_selector(name))) != 1:
            raise ValueError('Eigener Mac als AirDrop-Ziel nicht eindeutig; nichts gesendet.')

    def send(self, name):
        self.ensure_mac(name)
        self.ui.tap('-ios predicate string', self.mac_selector(name))

    def open_files(self, folder):
        """Beobachtete iOS-Dateien-Texte und Accessibility-Elemente verwenden.

        Nur den bereits ausgewählten Zielordner verwenden. Keine geratene Navigation
        durch andere iCloud-Verzeichnisse. Bei abweichender Ansicht stoppen.
        """
        for _ in range(3):
            source = self.ui.source()
            nodes = [n for n in ET.fromstring(source).iter() if n.get('visible') == 'true']
            if any(n.get('label') == 'Save to Files' or n.get('name') == 'Save to Files' for n in nodes):
                break
            if any(n.get('label') == 'View More' or n.get('name') == 'View More' for n in nodes):
                self.tap_unique_label('View More')
            else:
                # Bereits gezeigtes Teilen-Menü begrenzt nach unten scrollen, keine Koordinaten.
                views = self.ui.driver.find_elements('class name', 'XCUIElementTypeScrollView')
                visible = [view for view in views if view.is_displayed()]
                if len(visible) != 1:
                    raise ValueError('Save to Files nicht sichtbar und Share-Sheet-Scrollbereich nicht eindeutig. Bitte Menü einmal selbst erweitern.')
                self.ui.driver.execute_script('mobile: scroll', {'direction': 'down', 'elementId': visible[0].id})
        else:
            raise ValueError('Save to Files nach begrenztem Scrollen nicht gefunden.')
        self.tap_unique_label('Save to Files')
        self.ui.wait(lambda source: picker_matches(source, folder), description='iCloud-Zielprüfung im Dateien-Dialog')

    def tap_unique_label(self, label):
        self.ui.source()  # Sperre/Alerts prüfen.
        # Der sichtbare Text ist belegt, sein Accessibility-Typ erst am Gerät zu prüfen.
        predicate = '(label == ' + json.dumps(label) + ' OR name == ' + json.dumps(label) + ')'
        matches = self.ui.driver.find_elements('-ios predicate string', predicate)
        actionable = [element for element in matches if element.is_displayed()
                      and element.get_attribute('type') in ('XCUIElementTypeButton', 'XCUIElementTypeCell')]
        if len(actionable) != 1:
            raise ValueError('Speicherelement nicht eindeutig über beobachteten Text adressierbar; UI-Inspektion erforderlich.')
        actionable[0].click()

    def save_file(self, folder, filename, original_name_pattern=r'\d{8}_\d{6}(?:\.pdf)?'):
        if not re.fullmatch(r'appium-[a-f0-9]{32}\.(?:pdf|png|jpg|jpeg)', filename):
            raise ValueError('Nur kollisionssicherer projektgenerierter Name mit unterstütztem Originalformat erlaubt.')
        if not picker_matches(self.ui.source(), folder):
            raise ValueError('iCloud-Speicherziel weicht ab. Bitte einmal Desktop/appium-share im Dateien-Dialog auswählen.')
        fields = [element for element in self.ui.driver.find_elements('accessibility id', 'DOCPicker.filenameTextField') if element.is_displayed()]
        if len(fields) != 1:
            raise ValueError('Save-as-Feld nicht eindeutig. Keine anderen Textfelder verändert.')
        value = fields[0].get_attribute('value') or ''
        stem = filename.rsplit('.', 1)[0]
        planned = (filename, stem)
        if value not in planned and not re.fullmatch(original_name_pattern, value):
            raise ValueError('Dateiname entspricht nicht dem beobachteten Exportformat; UI-Inspektion erforderlich.')
        if value != stem:
            fields[0].clear()
            # iOS hängt die Endung des tatsächlichen Quelldokuments selbst an.
            fields[0].send_keys(stem)
        if fields[0].get_attribute('value') not in planned:
            raise ValueError('Eindeutiger Dateiname nicht bestätigt; nicht gespeichert.')
        if not picker_matches(self.ui.source(), folder):
            raise ValueError('Speicherziel während Namenseingabe nicht mehr bestätigt; angehalten.')
        self.ui.tap('accessibility id', 'DOCPicker.actionButton')


def picker_matches(xml, folder):
    root = ET.fromstring(xml)
    nodes = [n for n in root.iter() if n.get('visible') == 'true']
    nav_nodes = [n for bar in nodes if bar.get('name') == 'FullDocumentManagerViewControllerNavigationBar'
                 for n in bar.iter() if n.get('visible') == 'true']
    # Aktueller Navigationskopf, nicht ein zufällig gleichnamiger Eintrag in der Dateiliste.
    title = any(value == folder or value.startswith(folder + ', ')
                for n in nav_nodes for value in (n.get('label') or '', n.get('name') or ''))
    # Der interne Provider-Root kann „iCloud Drive“ heißen, obwohl der Nav-Kopf den
    # bereits ausgewählten Unterordner zeigt. Zielordner ausschließlich dort prüfen.
    provider = any(n.get('name', '').startswith('DOC.browsingRoot Source: com.apple.CloudDocs.iCloudDriveFileProvider/')
                   for n in nodes)
    cloud = provider or any('Synced with iCloud' in (n.get('label', '') + n.get('name', '')) for n in nodes)
    save = any(n.get('name') == 'DOCPicker.actionButton' or n.get('label') == 'Save' or n.get('name') == 'Save' for n in nav_nodes)
    return title and cloud and save
