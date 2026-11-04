"""Rossmann-Filialbons; beobachtete Navigation, keine Online-/Couponaktionen."""
from dataclasses import dataclass
from datetime import datetime
import json,re
import xml.etree.ElementTree as ET
from ..ui import NativeUI
from ..parsing import MONEY,cents
from ..parsers.rossmann import fiscal_identity

@dataclass(frozen=True)
class Entry:
    label:str
    date:str
    amount:int


def list_entries(xml):
    rows=[];root=ET.fromstring(xml)
    # Reale Liste: Datum, Betrag und Filiale sind aufeinanderfolgende Geschwister.
    for parent in root.iter():
        children=list(parent)
        for i,n in enumerate(children):
            m=re.fullmatch(r'Einkauf vom (\d{2}\.\d{2}\.\d{2})',n.get('label',''))
            if not m or n.get('visible')!='true':continue
            if i+1>=len(children):raise ValueError('Rossmann-Listensumme fehlt.')
            value=children[i+1].get('label','');amount=re.fullmatch('('+MONEY+r')\s*€',value)
            if not amount:raise ValueError('Rossmann-Listensumme nicht eindeutig.')
            rows.append(Entry(n.get('label'),datetime.strptime(m[1],'%d.%m.%y').date().isoformat(),cents(amount[1])))
    if len({r.label for r in rows})!=len(rows):raise ValueError('Mehrere Rossmann-Bons am selben Tag; Selektor nicht eindeutig, angehalten.')
    return rows


def receipt_segments(xml):
    root=ET.fromstring(xml)
    if not any(n.get('type')=='XCUIElementTypeNavigationBar' and n.get('name')=='Digitaler Bon' for n in root.iter()):return None
    parts=[]
    for n in root.iter():
        label=n.get('label','')
        if n.get('type')=='XCUIElementTypeOther' and n.get('visible')=='true' and len(label)>80:
            parts.extend(line for line in label.splitlines() if line.strip())
    parts=list(dict.fromkeys(parts))
    return parts if fiscal_identity('\n'.join(parts)) and sum(map(len,parts))>=80 else None


class Rossmann(NativeUI):
    export_name_pattern=r'ROSSMANN-Bon-\d{4}-\d{2}-\d{2}-T\d{6}-VKST-\d+(?:\.pdf)?'

    def open_list(self):
        xml=self.source()
        if self.has(xml,'Digitaler Bon'):
            self.close_receipt();return
        if list_entries(xml):return
        if not self.has(xml,'MEINE EINKÄUFE'):
            self.tap('-ios predicate string','type == "XCUIElementTypeOther" AND name == "Mehr"')
            self.wait(lambda x:self.has(x,'MEINE EINKÄUFE'))
        self.tap('accessibility id','MEINE EINKÄUFE')
        self.wait(lambda x:list_entries(x),description='Rossmann-Filialbonliste')

    def entries(self):return list_entries(self.source())

    def open_receipt(self,entry):
        self.tap('-ios predicate string','type == "XCUIElementTypeStaticText" AND label == '+json.dumps(entry.label,ensure_ascii=False))
        parts=self.wait(receipt_segments,description='Rossmann-Bontext mit Fiskalsignatur')
        return dict(merchant='rossmann',date=entry.date,total_cents=entry.amount,text='\n'.join(parts),receipt_segments=parts)

    def share(self):
        self.tap('accessibility id','more_bar_button_item')
        self.wait(lambda x:self.has(x,'share_action'))
        self.tap('accessibility id','share_action')
        self.wait(lambda x:self.has(x,'UIActivityContentView'))

    def close_receipt(self):
        self.wait(lambda x:self.has(x,'Digitaler Bon'))
        self.tap('accessibility id','BackButton')
        self.wait(lambda x:list_entries(x))

    def scroll(self,direction='down'):
        if direction not in ('up','down'):raise ValueError('Unzulässige Scrollrichtung.')
        self.source()
        views=[v for v in self.driver.find_elements('class name','XCUIElementTypeScrollView') if v.is_displayed()]
        if len(views)!=1:raise ValueError('Rossmann-Filialbonliste nicht eindeutig scrollbar.')
        self.driver.execute_script('mobile: scroll',{'direction':direction,'elementId':views[0].id,'distance':.5})
