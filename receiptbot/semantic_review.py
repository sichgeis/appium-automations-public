"""Kandidaten und Export einer im Chat visuell geprüften Bon-Auswertung.

Kein externer Modellaufruf. Gespeicherte Modellentscheidungen sind lokal,
originalhashgebunden und werden vor jedem CSV-Export erneut validiert.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import re
from .parsing import MONEY, cents, read_pdf
from .archive import file_digest
from .reporting import atomic_write


def kaufland_candidates(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    start = next(i for i,l in enumerate(lines) if re.fullmatch(r'Preis\s+EUR', l)) + 1
    end = next(i for i,l in enumerate(lines[start:],start) if re.fullmatch(r'Summe\s+'+MONEY, l, re.I))
    items, notes = [], []
    pending = None
    for n,line in enumerate(lines[start:end], start+1):
        if re.fullmatch(r'Zwischensumme\s+'+MONEY, line, re.I):
            notes.append(dict(line=n,text=line,type='subtotal'));continue
        match = re.fullmatch(r'(.+?)\s+('+MONEY+r')(?:\s+([A-Z]))?', line)
        if not match:
            if pending:notes.append(dict(line=pending[0],text=pending[1],type='unassigned_text'))
            pending=(n,line);continue
        name, amount, tax = match.groups()
        quantity=unit=unit_price=None
        multi=re.fullmatch(r'(?:(.+?)\s+)?(\d+)\s*\*\s*('+MONEY+r')',name)
        weight=re.fullmatch(r'(?:(.+?)\s+)?(\d+,\d{1,3})\s+(kg|g|l|ml)',name)
        sources=[dict(line=n,text=line)]
        if multi or weight:
            m=multi or weight
            if multi:
                name,quantity,price=m.groups();unit='piece';unit_price=cents(price)
            else:
                name,quantity,unit=m.groups();quantity=quantity.replace(',','.')
            if name is None:
                if pending is None:raise ValueError('Mengenzeile ohne Namen; Modellentscheidung erforderlich.')
                name=pending[1];sources.insert(0,dict(line=pending[0],text=pending[1]));pending=None
        if pending:
            notes.append(dict(line=pending[0],text=pending[1],type='unassigned_text'));pending=None
        value=cents(amount)
        kind='discount' if 'rabatt' in name.casefold() else 'deposit' if any(s in name.casefold() for s in ('pfand','leergut')) else 'refund' if value<0 else 'item'
        items.append(dict(description=name,quantity=quantity,unit=unit,unit_price_cents=unit_price,
            amount_cents=value,tax_code=tax,kind=kind,raw_line='\n'.join(s['text'] for s in sources),source_lines=sources))
    if pending:notes.append(dict(line=pending[0],text=pending[1],type='unassigned_text'))
    return items,notes


def prepare(index_path, destination):
    records=json.loads(Path(index_path).read_text())
    out=[]
    for r in records:
        p=deepcopy(r['parsed'])
        p['index']=r['index']
        p['original_size']=Path(r['source']).stat().st_size
        if p['merchant']=='kaufland':p['items'],p['review_notes']=kaufland_candidates(read_pdf(r['source']))
        else:p['review_notes']=[dict(type='unassigned_text',text=l) for l in p.get('unparsed_lines',[])]
        for i,item in enumerate(p['items'],1):item['position']=i
        p['difference_cents']=p['total_cents']-sum(i['amount_cents'] for i in p['items'])
        out.append(p)
    atomic_write(Path(destination),lambda f:json.dump(out,f,ensure_ascii=False,indent=2))
    return out


def enrich_payments(record, text):
    """Beobachtete Kontroll-/Zahlungszeilen getrennt vom Artikelblock."""
    record['fiscal_total_cents']=record['total_cents']
    record['payment_offsets']=[]
    if record['merchant']=='dm':
        m=re.search(r'Partner-Rabatte auf rabattfähige Artikel\s*\n(.*?)Zu zahlender Betrag EUR\s+('+MONEY+r')',text,re.S)
        if m:
            for line in m[1].splitlines():
                d=re.fullmatch(r'(.+?)\s+('+MONEY+r')\s*',line.strip())
                if d:
                    record['items'].append(dict(description=d[1],amount_cents=cents(d[2]),kind='discount',
                        quantity=None,unit=None,unit_price_cents=None,tax_code=None,raw_line=line.strip(),
                        scope='partner_discount_after_fiscal_total'))
            record['total_cents']=cents(m[2])
    elif record['merchant']=='kaufland':
        lines=[l.strip() for l in text.splitlines() if l.strip()]
        end=next(i for i,l in enumerate(lines) if re.fullmatch(r'Summe\s+'+MONEY,l,re.I))
        for line in lines[end+1:]:
            if line.startswith('Steuer'):break
            m=re.fullmatch(r'(Coupon|Gutschein)\s+('+MONEY+r')',line)
            if m:record['payment_offsets'].append(dict(description=m[1],amount_cents=cents(m[2]),source=line))
    for i,item in enumerate(record['items'],1):item['position']=i
    record['cash_outflow_cents']=record['total_cents']-sum(p['amount_cents'] for p in record['payment_offsets'])
    record['difference_cents']=record['total_cents']-sum(i['amount_cents'] for i in record['items'])
    return record


def validate_review(receipts, canonical=None):
    """Unabhängige Prüfungen: keine Summenerzwingung oder stillen Ergänzungen."""
    from decimal import ROUND_HALF_UP
    seen=set()
    for p in receipts:
        key=(p['merchant'],p['sha256'])
        if key in seen:raise ValueError('Doppelter Bon in der Neuauswertung.')
        seen.add(key)
        if canonical is not None and key not in canonical:raise ValueError('Bon nicht im verifizierten Archiv.')
        expected=canonical[key] if canonical is not None else (p['original_size'],p['sha256'])
        if file_digest(Path(p['source']))!=expected:raise ValueError('Originalhash abweichend.')
        if not p.get('visual_reviewed') or not p.get('visual_evidence'):raise ValueError('Visuelle Prüfung fehlt.')
        for evidence in p['visual_evidence']:
            from hashlib import sha256
            if sha256(Path(evidence['path']).read_bytes()).hexdigest()!=evidence['sha256']:
                raise ValueError('Visueller Prüfnachweis verändert.')
        if sum(i['amount_cents'] for i in p['items'])!=p['total_cents']:
            raise ValueError('Positionssumme stimmt nicht mit Zahl-/Bonbetrag überein.')
        fiscal=sum(i['amount_cents'] for i in p['items'] if i.get('scope')!='partner_discount_after_fiscal_total')
        if fiscal!=p['fiscal_total_cents']:raise ValueError('Steuerliche Bonsumme nicht unabhängig abgestimmt.')
        if p.get('printed_cash_outflow_cents') != p['cash_outflow_cents']:
            raise ValueError('Gedruckter Zahlungsbetrag nicht unabhängig bestätigt.')
        if p['taxes'] and sum(t['gross_cents'] for t in p['taxes'])!=p['fiscal_total_cents']:
            raise ValueError('Steueraufteilung passt nicht zur steuerlichen Bonsumme.')
        if p['total_cents']-sum(x['amount_cents'] for x in p['payment_offsets'])!=p['cash_outflow_cents']:
            raise ValueError('Zahlungsabstimmung abweichend.')
        for i,item in enumerate(p['items'],1):
            if item['position']!=i:raise ValueError('Positionsnummern nicht lückenlos.')
            if not item.get('category') or not re.search(r'[^\W\d_]',item['description']):
                raise ValueError('Kategorie oder Artikelbezeichnung fehlt.')
            if re.fullmatch(r'(?:Zwischensumme|Summe|Subtotal)',item['description'],re.I):
                raise ValueError('Summenzeile als Position gesperrt.')
            if item['kind'] not in ('item','discount','refund','deposit'):
                raise ValueError('Unbekannte oder künstliche Buchungsart gesperrt.')
            quantity=item.get('quantity');price=item.get('unit_price_cents')
            if quantity is not None and price is not None:
                calculated=int((Decimal(quantity)*price).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                if calculated!=item['amount_cents']:
                    raise ValueError('Menge mal Einzelpreis passt nicht zum Positionsbetrag.')
    if canonical is not None and seen!=set(canonical):raise ValueError('Nicht alle verifizierten Bons enthalten.')


def export_reviewed(data, output):
    from collections import defaultdict
    from .workflow import Exports
    output=Path(output)
    rows=json.loads((output/'llm_review/reviewed_receipts.json').read_text())
    canonical={(r['merchant'],r['sha256']):(r['byte_count'],r['sha256']) for r in Exports(data,output).originals()}
    validate_review(rows,canonical)
    entries=[];controls=[]
    for p in rows:
        key=p['merchant']+':'+p['sha256']
        for item in p['items']:
            amount=item['amount_cents'];discount=amount if item['kind']=='discount' else None
            rates={t['rate'] for t in p['taxes'] if t['code']==item.get('tax_code')}
            entries.append(dict(Haendler={'lidl':'Lidl Plus','dm':'dm','rossmann':'Rossmann','kaufland':'Kaufland'}[p['merchant']],
                Filiale=p['branch'],Datum=p['date'],Uhrzeit=p.get('time'),Monat=p['date'][:7],Bon_ID=p.get('receipt_id'),Bon_Schluessel=key,
                Position=item['position'],Buchungsart=item['kind'],Item=item['description'],Kategorie=item['category'],Unterkategorie=item['subcategory'],
                Kategorie_Status=item['category_status'],Menge=item.get('quantity'),Einheit=item.get('unit'),
                Einzelpreis=money(item.get('unit_price_cents')),Einzelpreis_Cent=item.get('unit_price_cents'),
                Buchungsbetrag=money(amount),Buchungsbetrag_Cent=amount,Rabatt=money(-discount) if discount is not None else None,
                Rabatt_Cent=-discount if discount is not None else None,Rabatt_Zuordnung=item.get('allocation'),Bezug_Position=item.get('related_position'),
                Waehrung=p['currency'],Steuercode=item.get('tax_code'),Steuersatz_Prozent=next(iter(rates)) if len(rates)==1 else None,
                Pruefstatus=item['review_status'],Originalzeile=item['raw_line'],Quelldatei=p['source'],SHA256=p['sha256'],Originalformat=p['original_format']))
        controls.append(dict(Datum=p['date'],Monat=p['date'][:7],Haendler=p['merchant'],Bon_Schluessel=key,
            Steuerliche_Bonsumme_Cent=p['fiscal_total_cents'],Ausgaben_nach_Rabatten_Cent=p['total_cents'],
            Zahlungsanrechnung_Cent=sum(x['amount_cents'] for x in p['payment_offsets']),
            Kartenzahlung_oder_Erstattung_Cent=p['cash_outflow_cents'],Positionen=len(p['items']),Differenz_Cent=0,
            Zahlungsanrechnungen_JSON=json.dumps(p['payment_offsets'],ensure_ascii=False),SHA256=p['sha256']))
        # Dauerhaftes strukturiertes Ergebnis je Original; nicht aus alten CSVs abgeleitet.
        atomic_write(output/'llm_review/receipts'/f"{p['merchant']}-{p['sha256']}.json",lambda f,p=p:json.dump(p,f,ensure_ascii=False,indent=2))
    destination=output/'reports'
    write_table(destination/'buchungen_llm.csv',entries)
    focused=[r for r in entries if r['Monat'] in ('2026-09','2026-10')]
    write_table(destination/'buchungen_llm_september_oktober.csv',focused)
    write_table(destination/'belege_llm_kontrolle.csv',controls)
    groups=defaultdict(lambda:dict(amount=0,count=0,discount=0))
    for row in entries:
        g=groups[(row['Monat'],row['Kategorie'],row['Unterkategorie'])]
        g['amount']+=row['Buchungsbetrag_Cent'];g['count']+=1;g['discount']+=row['Rabatt_Cent'] or 0
    summary=[dict(Monat=k[0],Kategorie=k[1],Unterkategorie=k[2],Ausgaben=money(v['amount']),Ausgaben_Cent=v['amount'],Rabatte=money(v['discount']),Rabatte_Cent=v['discount'],Positionen=v['count']) for k,v in sorted(groups.items())]
    write_table(destination/'monate_kategorien_llm.csv',summary)
    write_table(destination/'monate_kategorien_llm_september_oktober.csv',[r for r in summary if r['Monat'] in ('2026-09','2026-10')])
    # Erneute Integritätsprüfung nach den Ableitungen, keine Statusänderung im Archiv.
    validate_review(rows,canonical)
    return len(rows),len(entries),len(focused)


def money(value):
    return None if value is None else format(Decimal(value)/100,'.2f').replace('.',',')


def write_table(path, rows):
    """Deutschsprachiges CSV ohne wiederholte Bonsummen in jeder Artikelzeile."""
    import csv
    from .reporting import csv_cell
    if not rows:raise ValueError('Keine Zeilen für die angeforderte Auswertung.')
    fields=list(rows[0])
    numeric={f for f in fields if f.endswith('_Cent')}|{'Menge','Einzelpreis','Buchungsbetrag','Rabatt','Rabatte','Ausgaben','Position','Bezug_Position','Positionen','Steuersatz_Prozent'}
    def write(h):
        writer=csv.DictWriter(h,fieldnames=fields,delimiter=';');writer.writeheader()
        for row in rows:
            safe={}
            for k,v in row.items():
                if k in numeric and v is not None:
                    if not Decimal(str(v).replace(',','.')).is_finite():raise ValueError('Ungültige Zahl.')
                    safe[k]=str(v).replace('.',',')
                else:safe[k]=csv_cell(v)
            writer.writerow(safe)
    atomic_write(Path(path),write,encoding='utf-8-sig')


def main():
    from .session import ROOT
    count,items,focused=export_reviewed(ROOT/'data',ROOT/'output')
    print(f'{count} visuell im Chat geprüfte Bons, {items} Positionen; davon {focused} im September/Oktober. Alle Centkontrollen bestanden.')


if __name__=='__main__':main()
