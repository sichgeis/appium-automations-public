"""Beobachtetes Rossmann-PDF mit Europräfix und Unicode-Füllzeichen."""
from datetime import datetime
import re
from ..parsing import MONEY,cents


def clean(text):
    return text.replace('\ufe0f',' ')


def fiscal_identity(text):
    text=clean(text)
    counters=re.findall(r'Signaturzähler:\s*(\d+)',text)
    signatures=re.findall(r'Signatur:\s*([A-Za-z0-9+/=\s]+?)\nStart:',text)
    if len(counters)==len(signatures)==1:
        return dict(signature_counter=counters[0],fiscal_signature=re.sub(r'\s+','',signatures[0]))
    return {}


def parse_rossmann(text):
    text=clean(text);lines=[l.strip() for l in text.splitlines() if l.strip()]
    p=dict(merchant='rossmann',receipt_id=None,date=None,time=None,currency=None,total_cents=None,
           branch=None,register=None,taxes=[],items=[],warnings=[],unparsed_lines=[],parser_version=1)
    if not re.search(r'rossmann',text,re.I):p['warnings'].append('merchant_not_found')
    totals={cents(m[1]) for l in lines if (m:=re.fullmatch(r'Summe:\s*€\s*('+MONEY+r')',l))}
    if len(totals)==1:p['total_cents']=totals.pop();p['currency']='EUR'
    else:p['warnings'].append('total_missing_or_ambiguous')
    headers=[m for l in lines if (m:=re.match(r'^(\d{2}\.\d{2}\.\d{2}),\s*(\d{2}:\d{2})\s*/',l))]
    if len(headers)==1:
        try:p['date']=datetime.strptime(headers[0][1],'%d.%m.%y').date().isoformat()
        except ValueError:pass
        p['time']=headers[0][2]
    if not p['date']:p['warnings'].append('date_missing_or_ambiguous')
    p.update(fiscal_identity(text))
    subtotal=next((i for i,l in enumerate(lines) if l.startswith('Zwischensumme:')),None)
    # Artikel-EAN bzw. beobachtete interne Kennung D... bezeichnet den Artikel, keine Bon-ID.
    if subtotal is not None:
        for l in lines[:subtotal]:
            m=re.fullmatch(r'(?:(-?\d+)X\s+)?(\d{13}|D\d+)\s+(.+?)\s+€\s*('+MONEY+r')(?:\s+|\s*\*)\s*([A-Z])',l)
            if not m:
                if re.match(r'(?:(?:-?\d+)X\s+)?(?:\d{13}|D\d+)\s',l):
                    p['warnings'].append('unparsed_item_line')
                    p['unparsed_lines'].append(l)
                continue
            quantity,code,name,value,tax=m.groups();unit_price=None
            price=re.fullmatch(r'(.+?)\s+€\s*('+MONEY+r')',name)
            if price:name=price[1];unit_price=cents(price[2])
            amount=cents(value)
            if quantity and unit_price is not None and int(quantity)*unit_price!=amount:p['warnings'].append('item_quantity_price_mismatch')
            p['items'].append(dict(description=name,quantity=quantity,unit='piece' if quantity else None,
                unit_price_cents=unit_price,amount_cents=amount,tax_code=tax,
                kind='refund' if (quantity and int(quantity)<0) or amount<0 else 'deposit' if 'pfand' in name.casefold() else 'item',raw_line=l))
        discount=next((i for i,l in enumerate(lines) if l=='Deine Coupon-Ersparnis heute:'),None)
        end=next((i for i,l in enumerate(lines) if re.fullmatch(r'Summe:\s*€\s*'+MONEY,l)),None)
        if discount is not None and end is not None:
            for l in lines[discount+1:end]:
                if re.fullmatch(r'[-_=\s]+',l):continue
                summary=re.fullmatch(r'Du hast insgesamt\s*€\s*('+MONEY+r')\s+gespart!',l)
                if summary:
                    p['discount_total_cents']=cents(summary[1])
                    continue
                m=re.fullmatch(r'(?:\d{13}\s+)?(.+?)\s+€\s*('+MONEY+r')',l)
                if m:
                    p['items'].append(dict(description=m[1],quantity=None,unit=None,unit_price_cents=None,
                        amount_cents=-cents(m[2]),tax_code=None,kind='discount',raw_line=l))
                else:
                    p['warnings'].append('unparsed_discount_line')
                    p['unparsed_lines'].append(l)
        if not p['items'] or sum(i['amount_cents'] for i in p['items'])!=p['total_cents']:p['warnings'].append('item_sum_mismatch')
        if p.get('discount_total_cents') is not None and -sum(i['amount_cents'] for i in p['items'] if i['kind']=='discount')!=p['discount_total_cents']:
            p['warnings'].append('discount_sum_mismatch')
    else:p['warnings'].append('item_layout_not_recognized')
    for l in lines:
        m=re.fullmatch(r'([A-Z])\s+(\d+(?:,\d+)?)%:\s*€\s*('+MONEY+r')\s+€\s*('+MONEY+r')\s+€\s*('+MONEY+r')',l)
        if m:
            row=dict(code=m[1],rate=m[2].replace(',','.'),net_cents=cents(m[3]),tax_cents=cents(m[4]),gross_cents=cents(m[5]))
            p['taxes'].append(row)
            if row['net_cents']+row['tax_cents']!=row['gross_cents']:p['warnings'].append('tax_sum_mismatch')
    if p['taxes'] and sum(t['gross_cents'] for t in p['taxes'])!=p['total_cents']:p['warnings'].append('tax_total_mismatch')
    p['warnings']=sorted(set(p['warnings']))
    return p
