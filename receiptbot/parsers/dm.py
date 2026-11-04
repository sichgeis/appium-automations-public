"""dm-PDF-Textebene; nur am Original beobachtete Zeilenformate."""
from datetime import datetime
import re
from ..parsing import MONEY,cents,normalized


def quicklook_total(parts):
    """Gedruckte Gesamtsumme, auch bei Abschnittsgrenzen mitten im Betrag."""
    values = [cents(m[1]) for m in re.finditer(r'(?<!zwischen)summeeur('+MONEY+r')',normalized(''.join(parts)))]
    if len(values) != 1:
        raise ValueError('Gedruckte dm-SUMME in der Vorschau nicht eindeutig; kein Export.')
    return values[0]


def quicklook_segment_matches(segment, pdf_text):
    """Exakter Abschnitt oder exakte Tokenanzahlen eines zusammenhängenden Tabellenblocks.

    Quick Look liest teils erst die Namensspalte, dann die Preisspalte. Nur für
    einen solchen Abschnitt mit expliziter SUMME-Zeile ist die Reihenfolge frei;
    Wörter, Kennzeichen, Zahlen und ihre Häufigkeiten müssen identisch bleiben.
    Die fiskalische Identität prüft der Aufrufer zusätzlich zwingend.
    """
    from collections import Counter
    from ..parsing import normalized
    if normalized(segment) in normalized(pdf_text):
        return True
    if not re.search(r'\bSUMME EUR\s+' + MONEY + r'(?![\d,])', segment):
        return False
    expected = segment.casefold().split()
    received = pdf_text.casefold().split()
    length = len(expected)
    if length < 12 or length > len(received):
        return False
    wanted = Counter(expected)
    window = Counter(received[:length])
    if window == wanted:
        return True
    for index in range(length, len(received)):
        leaving = received[index-length]
        window[leaving] -= 1
        if window[leaving] == 0:
            del window[leaving]
        window[received[index]] += 1
        if window == wanted:
            return True
    return False


def quicklook_segments_match(parts, pdf_text):
    """Begrenzte Reparatur von Quick-Look-Abschnittsgrenzen, kein Textverlust.

    iOS kann mitten im Wort/Betrag trennen. Zwischen höchstens acht benachbarten
    Abschnitten kommt deshalb nur kein oder ein Leerzeichen infrage. Alle
    nicht betroffenen Abschnitte müssen weiterhin unabhängig exakt passen.
    """
    from itertools import product
    if not parts:
        return False
    missing = [i for i,p in enumerate(parts) if not quicklook_segment_matches(p,pdf_text)]
    if not missing:
        return True
    first, last = missing[0], missing[-1]
    for length in range(max(2,last-first+1), min(8,len(parts))+1):
        for start in range(max(0,last-length+1), min(first,len(parts)-length)+1):
            group = parts[start:start+length]
            for joins in product(('', ' '), repeat=length-1):
                merged = group[0] + ''.join(join+part for join,part in zip(joins,group[1:]))
                if quicklook_segment_matches(merged,pdf_text):
                    return True
    return False


def parse_dm(text):
    result=dict(merchant='dm',receipt_id=None,date=None,time=None,currency=None,total_cents=None,
                branch=None,register=None,taxes=[],items=[],warnings=[],unparsed_lines=[],parser_version=2)
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if not re.search(r'\bdm\.de\b',text,re.I):
        result['warnings'].append('merchant_not_found')
    totals={cents(m[1]) for line in lines if (m:=re.fullmatch(r'SUMME EUR\s+('+MONEY+r')',line))}
    if len(totals)==1:
        result['total_cents']=totals.pop();result['currency']='EUR'
    else:result['warnings'].append('total_missing_or_ambiguous')
    headers=[m for line in lines if (m:=re.fullmatch(r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})\s+\S+\s+\S+\s+\d+',line))]
    if len(headers)==1:
        try:result['date']=datetime.strptime(headers[0][1],'%d.%m.%Y').date().isoformat()
        except ValueError:pass
        result['time']=headers[0][2]
    if not result['date']:result['warnings'].append('date_missing_or_ambiguous')
    fiscal=re.findall(r'SN-Kasse:\s*(\S+)\s+TA-Nummer:\s*(\d+)',text)
    if len(fiscal)==1:result['register'],result['tse_transaction']=fiscal[0]
    serial=re.findall(r'SN-TSE:\s*([a-fA-F0-9]+)\s*\n\s*([a-fA-F0-9]+)\s*\n',text)
    if len(serial)==1:result['tse_serial']=''.join(serial[0])
    start=lines.index(headers[0][0])+1 if len(headers)==1 else None
    end=next((i for i,l in enumerate(lines) if re.fullmatch(r'SUMME EUR\s+'+MONEY,l)),None)
    if start is not None and end is not None and start<=end:
        discount_block = False
        for line in lines[start:end]:
            subtotal = re.fullmatch(r'Zwischensumme\s+(' + MONEY + r')',line)
            if subtotal:
                if sum(i['amount_cents'] for i in result['items']) != cents(subtotal[1]):
                    result['warnings'].append('subtotal_mismatch')
                continue
            if line == 'dm-Rabatte auf rabattfähige Artikel':
                discount_block = True
                continue
            if discount_block:
                discount = re.fullmatch(r'(.+?)\s+(' + MONEY + r')',line)
                if not discount:
                    result['warnings'].append('unparsed_discount_line')
                    result['unparsed_lines'].append(line)
                    continue
                amount = cents(discount[2])
                if amount > 0:
                    result['warnings'].append('positive_discount_amount')
                result['items'].append(dict(description=discount[1],quantity=None,unit=None,
                    unit_price_cents=None,amount_cents=amount,tax_code=None,kind='discount',raw_line=line))
                continue
            m=re.fullmatch(r'(.+?)\s+('+MONEY+r')\s+(§?)(\d)',line)
            if not m:
                result['warnings'].append('unparsed_item_line');result['unparsed_lines'].append(line);continue
            name=m[1];quantity=unit_price=None
            multi=re.fullmatch(r'(\d+)x\s+('+MONEY+r')\s+(.+)',name)
            if multi:quantity=multi[1];unit_price=cents(multi[2]);name=multi[3]
            amount=cents(m[2])
            if quantity and int(quantity)*unit_price!=amount:result['warnings'].append('item_quantity_price_mismatch')
            kind='discount' if 'rabatt' in name.casefold() else 'deposit' if 'pfand' in name.casefold() else 'refund' if amount<0 else 'item'
            result['items'].append(dict(description=name,quantity=quantity,unit='piece' if quantity else None,
                unit_price_cents=unit_price,amount_cents=amount,tax_code=m[4],kind=kind,raw_line=line,
                discount_excluded=bool(m[3])))
        if sum(i['amount_cents'] for i in result['items'])!=result['total_cents']:result['warnings'].append('item_sum_mismatch')
    else:result['warnings'].append('item_layout_not_recognized')
    for line in lines:
        m=re.fullmatch(r'(\d)=(\d+,\d{2})%\s+('+MONEY+r')\s+('+MONEY+r')\s+('+MONEY+r')',line)
        if m:
            row=dict(code=m[1],rate=m[2].replace(',','.'),gross_cents=cents(m[3]),net_cents=cents(m[4]),tax_cents=cents(m[5]))
            result['taxes'].append(row)
            if row['gross_cents']!=row['net_cents']+row['tax_cents']:result['warnings'].append('tax_sum_mismatch')
    if result['taxes'] and sum(t['gross_cents'] for t in result['taxes'])!=result['total_cents']:result['warnings'].append('tax_total_mismatch')
    result['warnings']=sorted(set(result['warnings']))
    return result
