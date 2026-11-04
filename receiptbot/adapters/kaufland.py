"""Beobachtete Kaufland-6.20-Selektoren; weitere Geräteprüfung erforderlich."""
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from ..parsing import cents, parse_text
from ..pdf_identity import receipt_identity
from ..ui import NativeUI

MONTHS = {name: i for i, name in enumerate(('January', 'February', 'March', 'April', 'May',
    'June', 'July', 'August', 'September', 'October', 'November', 'December'), 1)}


@dataclass(frozen=True)
class Entry:
    label: str
    products: str
    total: str
    day: str
    amount: int

    @property
    def key(self):
        # Ausschließlich Navigation, ausdrücklich keine Bon-ID/Deduplizierungsidentität.
        return hashlib.sha256(json.dumps([self.label, self.products, self.total]).encode()).hexdigest()


def list_entries(xml):
    root = ET.fromstring(xml)
    result = []
    for parent in root.iter():
        children = list(parent)
        for i, node in enumerate(children):
            if node.get('name') != 'dateLabel' or node.get('visible') != 'true':
                continue
            following = children[i+1:i+3]
            if len(following) != 2 or [n.get('name') for n in following] != ['productsLabel', 'totalLabel']:
                raise ValueError('Kaufland-Bonliste hat eine unbekannte Struktur; angehalten.')
            label = node.get('label', '')
            match = re.fullmatch(r'([A-Za-z]+)\.(\d{2}|\d{1})\.(\d{4})', label)
            if not match or match[1] not in MONTHS:
                raise ValueError('Unbekanntes Datumsformat in Kaufland; keine geratenen Selektoren.')
            day = date(int(match[3]), MONTHS[match[1]], int(match[2])).isoformat()
            total = following[1].get('label', '')
            amount = re.fullmatch(r'(-?\d+(?:\.\d{3})*,\d{2})\s*€', total)
            if not amount:
                raise ValueError('Unbekanntes Summenformat in Bonliste.')
            result.append(Entry(label, following[0].get('label', ''), total, day, cents(amount[1])))
    if len({entry.key for entry in result}) != len(result):
        raise ValueError('Gleich aussehende Listeneinträge sind nicht eindeutig adressierbar. Keine Bons übersprungen.')
    return result


def xpath_literal(value):
    if '"' not in value:
        return '"' + value + '"'
    if "'" not in value:
        return "'" + value + "'"
    return 'concat(' + ', "\'", '.join('"' + part + '"' for part in value.split("'")) + ')'


class Kaufland(NativeUI):
    def open_list(self):
        xml = self.source()
        if self.has(xml, 'UIActivityContentView'):
            raise ValueError('Teilen-Menü ist noch offen. Vor neuem Lauf selbst schließen; kein erneutes Senden.')
        if self.has(xml, 'share') and self.has(xml, 'CloseButton'):
            self.tap('accessibility id', 'CloseButton')
            xml = self.source()
        if list_entries(xml):
            return
        if self.has(xml, 'Digital Receipts'):
            self.tap('accessibility id', 'Digital Receipts')
        elif self.has(xml, 'tab_profile'):
            self.tap('accessibility id', 'tab_profile')
            self.wait(lambda source: self.has(source, 'Digital Receipts'))
            self.tap('accessibility id', 'Digital Receipts')
        else:
            raise ValueError('Keine bekannte Kaufland-Startansicht. Bitte eingeloggte Startseite selbst öffnen.')
        self.wait(lambda source: list_entries(source), timeout=60, description='Kaufland-Bonliste öffnen')

    def entries(self):
        return self.wait(lambda source: list_entries(source), description='Kaufland-Bonliste nach dem Laden')

    def open_receipt(self, entry):
        # Datum allein kann mehrfach vorkommen: beobachtete Geschwisterstruktur mit prüfen.
        selector = ('//XCUIElementTypeButton[@name="dateLabel" and @label=' + xpath_literal(entry.label)
            + ' and following-sibling::*[1][@name="productsLabel" and @label=' + xpath_literal(entry.products)
            + '] and following-sibling::*[2][@name="totalLabel" and @label=' + xpath_literal(entry.total) + ']]')
        self.tap('xpath', selector)
        xml = self.wait(lambda source: source if self.has(source, 'share') and self.has(source, 'CloseButton') else None,
                        timeout=60, description='Kaufland-Bonansicht laden')
        texts = [n.get('label', '') for n in ET.fromstring(xml).iter()
                 if n.get('type') == 'XCUIElementTypeStaticText' and 'Kaufland' in n.get('label', '') and len(n.get('label', '')) > 200]
        if len(texts) != 1:
            raise ValueError('Vollständiger Bontext nicht eindeutig gefunden; kein Export.')
        parsed = parse_text(texts[0], 'kaufland')
        # Einige echte Bonvorschauen enthalten keine Datumszeile. In diesem Fall
        # dient nur die beobachtete Liste zur Auswahl; das Original-PDF muss Datum
        # und Summe weiterhin selbst bestätigen (validate_receipt bleibt streng).
        printed_date = re.search(r'\b(?:\d{2}[./-]\d{2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})\b', texts[0])
        missing_ui_date = parsed['date'] is None and not printed_date and not re.search(r'\b(?:Datum|Date|Start|Ende)\s*:', texts[0])
        if (parsed['date'] != entry.day and not missing_ui_date) or parsed['total_cents'] != entry.amount:
            raise ValueError('Geöffneter Bon passt nicht eindeutig zum Listeneintrag; angehalten.')
        return {'merchant': 'kaufland', 'date': entry.day, 'total_cents': entry.amount,
                'text': texts[0], 'navigation_key': entry.key, 'ui_date_missing': missing_ui_date,
                'ui_identity_unavailable': receipt_identity(parsed) is None}

    def share(self):
        self.tap('-ios predicate string', 'type == "XCUIElementTypeButton" AND name == "share"')
        self.wait(lambda source: self.has(source, 'UIActivityContentView'))

    def send_to_mac(self, name):
        from ..share_sheet import ShareSheetController
        ShareSheetController(self).send(name)

    def close_receipt(self):
        xml = self.source()
        if self.has(xml, 'UIActivityContentView'):
            # Begrenzte, elementbezogene Geste; keine Koordinaten und keine Export-Wiederholung.
            elements = self.driver.find_elements('accessibility id', 'UIActivityContentView')
            if len(elements) != 1:
                raise ValueError('Teilen-Menü nicht eindeutig schließbar; bitte selbst schließen.')
            self.driver.execute_script('mobile: swipe', {'direction': 'down', 'elementId': elements[0].id})
            self.wait(lambda source: not self.has(source, 'UIActivityContentView'))
        self.tap('accessibility id', 'CloseButton')
        self.wait(lambda source: list_entries(source), timeout=60, description='Kaufland-Bonliste nach Schließen laden')

    def rewind_list(self, max_steps=1000):
        previous = None
        unchanged = 0
        for _ in range(max_steps):
            current = tuple(entry.key for entry in self.entries())
            unchanged = unchanged + 1 if current == previous else 0
            if unchanged >= 2:
                return
            previous = current
            self.scroll('up')
        raise ValueError('Kaufland-Listenanfang nach begrenztem Scrollen nicht bestätigt.')

    def scroll(self, direction='down'):
        if direction not in ('up','down'):
            raise ValueError('Unzulässige Scrollrichtung.')
        self.source()
        views = self.driver.find_elements('class name', 'XCUIElementTypeScrollView')
        visible = [view for view in views if view.is_displayed()]
        if len(visible) != 1:
            raise ValueError('Bonlisten-Scrollbereich nicht eindeutig; angehalten.')
        self.driver.execute_script('mobile: scroll', {'direction': direction, 'elementId': visible[0].id})
        time.sleep(1.2)
