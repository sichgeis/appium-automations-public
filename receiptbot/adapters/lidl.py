"""Lidl-Plus-Navigation anhand realer deutscher UI; App-Exportformat PNG."""
from dataclasses import dataclass
from datetime import date
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from ..ui import NativeUI
from ..parsing import MONEY, cents, parse_text

MONTHS = {name: index for index,name in enumerate(('Januar','Februar','März','April','Mai','Juni',
    'Juli','August','September','Oktober','November','Dezember'),1)}


@dataclass(frozen=True)
class Entry:
    label: str
    day: int
    month: int
    amount: int

    @property
    def key(self):
        return hashlib.sha256(self.label.encode()).hexdigest()


def list_entries(xml):
    entries = []
    for node in ET.fromstring(xml).iter():
        label = node.get('label') or node.get('name') or ''
        if node.get('type') != 'XCUIElementTypeCell' or node.get('visible') != 'true' or not label.startswith('Kassenbon vom '):
            continue
        match = re.match(r'Kassenbon vom (\d{1,2})\. ([A-Za-zÄÖÜäöüß]+) über (' + MONEY + r') €\.', label)
        if not match or match[2] not in MONTHS:
            raise ValueError('Lidl-Bonliste hat ein unbekanntes Datums-/Summenformat.')
        entries.append(Entry(label,int(match[1]),MONTHS[match[2]],cents(match[3])))
    if len({entry.key for entry in entries}) != len(entries):
        raise ValueError('Lidl-Listeneinträge nicht eindeutig; keine Bons übersprungen.')
    return entries


def receipt_text(xml):
    texts = [node.get('label','') for node in ET.fromstring(xml).iter()
             if node.get('type') == 'XCUIElementTypeStaticText' and node.get('visible') == 'true'
             and len(node.get('label','')) > 80 and re.search(r'zu zahlen\s+',node.get('label',''),re.I)]
    return texts[0] if len(texts) == 1 else None


class Lidl(NativeUI):
    export_suffix = '.png'
    export_name_pattern = r'PNG-Bild(?:\.png)?'

    def open_list(self):
        xml = self.wait(lambda x:x if list_entries(x) or receipt_text(x) or self.has(x,'Meine Kassenbons')
                        or self.has(x,'Weitere Optionen') or self.has(x,'Home') else None, description='Lidl-Startansicht')
        if self.has(xml,'FullDocumentManagerViewControllerNavigationBar'):
            raise ValueError('Lidl-Speicherdialog noch offen; vorhandenen Transfer zuerst klären.')
        if self.has(xml,'UIActivityContentView'):
            self.close_share()
            xml = self.source()
        if any(n.get('type')=='XCUIElementTypeNavigationBar' and n.get('name')=='Meine Kassenbons'
               and n.get('visible')=='true' for n in ET.fromstring(xml).iter()):
            self.wait(lambda x:list_entries(x))
            return
        if receipt_text(xml):
            self.close_receipt()
            return
        if list_entries(xml):
            return
        if not self.has(xml,'Meine Kassenbons'):
            if not self.has(xml,'Weitere Optionen'):
                self.tap('-ios predicate string','type == "XCUIElementTypeButton" AND name == "Home"')
                self.wait(lambda x:self.has(x,'Weitere Optionen'))
            self.tap('-ios predicate string','type == "XCUIElementTypeButton" AND name == "Weitere Optionen"')
            self.wait(lambda x:self.has(x,'Meine Kassenbons'))
        self.tap('-ios predicate string','type == "XCUIElementTypeButton" AND name == "Meine Kassenbons"')
        self.wait(lambda x:list_entries(x))

    def entries(self):
        return list_entries(self.source())

    def open_receipt(self, entry):
        import json
        self.tap('-ios predicate string','type == "XCUIElementTypeCell" AND label == ' + json.dumps(entry.label,ensure_ascii=False))
        text = self.wait(receipt_text, description='Lidl-Belegdetails')
        parsed = parse_text(text,'lidl')
        if not parsed['date']:
            raise ValueError('Lidl-Einkaufsdatum nicht eindeutig; kein Jahr aus dem Listentitel geraten.')
        day = date.fromisoformat(parsed['date'])
        if (day.day,day.month,parsed['total_cents']) != (entry.day,entry.month,entry.amount):
            raise ValueError('Lidl-Detail stimmt nicht eindeutig mit dem ausgewählten Listeneintrag überein.')
        return dict(merchant='lidl',date=parsed['date'],total_cents=parsed['total_cents'],text=text,navigation_key=entry.key)

    def share(self):
        self.tap('-ios predicate string','type == "XCUIElementTypeButton" AND name == "Weitere Optionen"')
        self.wait(lambda x:self.has(x,'Teilen'))
        self.tap('-ios predicate string','type == "XCUIElementTypeButton" AND name == "Teilen"')
        self.wait(lambda x:self.has(x,'UIActivityContentView'), description='iOS-Teilen-Menü für Lidl')

    def close_receipt(self):
        self.wait(lambda x:not self.has(x,'FullDocumentManagerViewControllerNavigationBar'))
        if self.has(self.source(),'UIActivityContentView'):
            self.close_share()
        self.wait(lambda x:receipt_text(x) or list_entries(x))
        if list_entries(self.source()):
            return
        self.tap('-ios predicate string','type == "XCUIElementTypeButton" AND name == "Zurück" AND visible == 1')
        self.wait(lambda x:list_entries(x))

    def close_share(self):
        self.tap('accessibility id','header.closeButton')
        self.wait(lambda x:not self.has(x,'UIActivityContentView'))

    def assert_period_covers(self, cutoff):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo('Europe/Berlin')).date()
        try:
            earliest = today.replace(year=today.year-1)
        except ValueError:
            earliest = today.replace(year=today.year-1,day=28)
        root = ET.fromstring(self.source())
        default_period = any(n.get('visible')=='true' and n.get('label')=='Datum: Letzte 12 Monate' for n in root.iter())
        if not default_period or cutoff < earliest:
            raise ValueError('Lidl-Datumsfilter deckt die gewünschte Untergrenze nicht nachweislich ab; angehalten.')

    def scroll(self,direction='down'):
        if direction not in ('up','down'):raise ValueError('Unzulässige Scrollrichtung.')
        self.source()
        tables = [table for table in self.driver.find_elements('class name','XCUIElementTypeTable') if table.is_displayed()]
        if len(tables) != 1:
            raise ValueError('Lidl-Bonliste nicht eindeutig scrollbar; angehalten.')
        self.driver.execute_script('mobile: scroll',{'direction':direction,'elementId':tables[0].id,'distance':.5})
        time.sleep(1.2)
