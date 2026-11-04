"""dm: nur beobachtete Einkäufe-/Quick-Look-Navigation, keine Warenkorbaktion."""
from dataclasses import dataclass
from datetime import datetime
import json,re
import xml.etree.ElementTree as ET
from ..ui import NativeUI
from ..parsing import MONEY,cents,parse_text
from ..parsers.dm import quicklook_total

@dataclass(frozen=True)
class Entry:
    label:str
    date:str
    amount:int


def list_entries(xml):
    root=ET.fromstring(xml)
    top=0.0
    bottom=float('inf')
    tabs={'Startseite','Produkte','Warenkorb','Coupons','Mein Konto'}
    for node in root.iter():
        if node.get('visible')!='true' or node.get('y') is None or node.get('height') is None:
            continue
        y,height=float(node.get('y')),float(node.get('height'))
        if node.get('type')=='XCUIElementTypeNavigationBar' or (node.get('type')=='XCUIElementTypeButton' and node.get('name')=='BackButton'):
            top=max(top,y+height)
        if node.get('type')=='XCUIElementTypeButton' and node.get('name') in tabs:
            bottom=min(bottom,y)
    rows=[]
    for n in root.iter():
        if n.get('type')!='XCUIElementTypeLink' or n.get('visible')!='true':continue
        if n.get('y') is not None and n.get('height') is not None:
            y,height=float(n.get('y')),float(n.get('height'))
            if height<=0 or y<top or y+height>bottom:
                continue
        label=n.get('label','')
        m=re.fullmatch(r'Im Markt eingekauft, Am (\d{2}\.\d{2}\.\d{4}), ('+MONEY+r')\s*€',label)
        if m:rows.append(Entry(label,datetime.strptime(m[1],'%d.%m.%Y').date().isoformat(),cents(m[2])))
    if len({r.label for r in rows})!=len(rows):raise ValueError('dm-Listeneinträge mehrdeutig; angehalten.')
    return rows


def quicklook_segments(xml):
    bodies=[n for n in ET.fromstring(xml).iter() if n.get('name')=='QLPDFViewControllerViewAccessibilityIdentifier']
    if len(bodies)!=1:return None
    # Quick Look liest eine Steuerkennziffern-Spalte separat; sie ist kein Textabschnitt.
    # PDFKit markiert einzelne korrekt positionierte Textfelder als unsichtbar.
    # Innerhalb genau dieses PDF-Dokuments deshalb auch deren Text lesen, aber
    # keine anderen/überlagerten App-Ansichten einbeziehen.
    parts=list(dict.fromkeys(n.get('label','') for n in bodies[0].iter()
        if n.get('type')=='XCUIElementTypeStaticText' and n.get('label')
        and not re.fullmatch(r'\d(?:\n\d)+',n.get('label',''))))
    return parts if sum(map(len,parts))>=80 and any('SN-Kasse:' in p and 'TA-Nummer:' in p for p in parts) and any('SN-TSE:' in p for p in parts) else None


class Dm(NativeUI):
    export_name_pattern=r'dm-eBon_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:\.pdf)?'

    def open_list(self):
        xml=self.source()
        if self.has(xml,'QLOverlayDoneButtonAccessibilityIdentifier'):
            self.tap('accessibility id','QLOverlayDoneButtonAccessibilityIdentifier');xml=self.source()
        if self.has(xml,'ebons-item-download-button'):
            self.tap('accessibility id','BackButton');xml=self.source()
        if list_entries(xml):return
        if not self.has(xml,'Meine Einkäufe'):
            self.tap('-ios predicate string','type == "XCUIElementTypeButton" AND name == "Mein Konto"')
            self.wait(lambda x:self.has(x,'Meine Einkäufe'))
        self.tap('-ios predicate string','type == "XCUIElementTypeStaticText" AND name == "Meine Einkäufe"')
        self.wait(lambda x:list_entries(x),timeout=60,description='dm-Einkaufsliste')

    def entries(self):
        xml=self.source()
        if not self.has(xml,'BackButton') or not self.has(xml,'Meine Einkäufe'):
            raise ValueError('dm ist nicht in der bestätigten Einkaufsliste; kein Scrollen/Export außerhalb dieser Ansicht.')
        return list_entries(xml)

    def open_receipt(self,entry):
        first = None
        for attempt in range(2):
            self.tap('-ios predicate string','type == "XCUIElementTypeLink" AND label == '+json.dumps(entry.label,ensure_ascii=False))
            self.wait(lambda x:self.has(x,'ebons-item-download-button'),timeout=60,description='dm-Einkaufsdetail nach Auswahl')
            self.tap('accessibility id','ebons-item-download-button')
            parts=self.wait(quicklook_segments,description='dm-PDF-Vorschau mit fiskalischen Kennungen')
            total=quicklook_total(parts)
            expected=dict(merchant='dm',date=entry.date,total_cents=total,text='\n'.join(parts),
                          quicklook_segments=parts,list_total_cents=entry.amount,ui_total_source='quicklook_summe')
            if total == entry.amount:
                return expected
            parsed=parse_text(expected['text'],'dm')
            identity=tuple(parsed.get(key) for key in ('register','tse_serial','tse_transaction'))
            if not all(identity):
                raise ValueError('Abweichender dm-Listenbetrag ohne eindeutige Fiskalidentität; angehalten.')
            observed=(total,identity)
            if first is not None:
                if first != observed:
                    raise ValueError('dm-Vorschau ändert Summe/Identität bei erneuter Auswahl; kein Export.')
                expected.update(list_total_mismatch=True,ui_total_source='quicklook_summe_confirmed_twice')
                return expected
            first=observed
            # Ausschließlich Navigation erneut ausführen, vor Teilen/Speichern.
            self.close_receipt()
        raise ValueError('dm-Bonzuordnung nicht bestätigt.')

    def share(self):
        self.tap('accessibility id','QLOverlayDefaultActionButtonAccessibilityIdentifier')
        self.wait(lambda x:self.has(x,'UIActivityContentView'),description='dm-Teilen-Menü')

    def close_receipt(self):
        self.wait(lambda x:self.has(x,'QLOverlayDoneButtonAccessibilityIdentifier'),description='dm-PDF-Schließen-Schaltfläche')
        self.tap('accessibility id','QLOverlayDoneButtonAccessibilityIdentifier')
        self.wait(lambda x:self.has(x,'ebons-item-download-button'),timeout=60,description='dm-Einkaufsdetail nach PDF-Schließen')
        self.tap('accessibility id','BackButton')
        self.wait(lambda x:list_entries(x),timeout=60,description='dm-Einkaufsliste nach Rückkehr')

    def scroll(self,direction='down'):
        if direction not in ('up','down'):raise ValueError('Unzulässige Scrollrichtung.')
        self.entries()  # Kontext prüfen, bevor eine Geste ausgeführt wird.
        views=[v for v in self.driver.find_elements('class name','XCUIElementTypeScrollView') if v.is_displayed()]
        if len(views)!=1:raise ValueError('dm-Einkaufsliste nicht eindeutig scrollbar.')
        self.driver.execute_script('mobile: scroll',{'direction':direction,'elementId':views[0].id,'distance':.5})
