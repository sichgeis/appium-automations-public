"""Beobachteter Lidl-Plus-Bontext; Bankbelegnummern sind keine Bon-IDs."""
from datetime import datetime
import re
from ..parsing import MONEY, cents


def parse_lidl(text):
    result = dict(merchant='lidl', receipt_id=None, date=None, time=None, currency=None,
                  total_cents=None, branch=None, register=None, taxes=[], items=[], warnings=[], unparsed_lines=[], parser_version=1)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not re.search(r'\blidl\b', text, re.I):
        result['warnings'].append('merchant_not_found_in_app_text')
    totals = {cents(m[1]) for line in lines if (m := re.fullmatch(r'zu zahlen\s+(' + MONEY + r')', line, re.I))}
    if len(totals) == 1:
        result['total_cents'] = totals.pop()
    else:
        result['warnings'].append('total_missing_or_ambiguous')
    if re.search(r'\bEUR\b', text):
        result['currency'] = 'EUR'
    dates = set()
    for value in re.findall(r'\b(?:\d{2}\.\d{2}\.\d{4}|\d{2}\.\d{2}\.\d{2})\b', text):
        try:
            dates.add(datetime.strptime(value, '%d.%m.%Y' if len(value) == 10 else '%d.%m.%y').date().isoformat())
        except ValueError:
            pass
    if len(dates) == 1:
        result['date'] = dates.pop()
    else:
        result['warnings'].append('date_missing_or_ambiguous')
    receipt_times = re.findall(r'\b\d{2}\.\d{2}\.\d{2}\s+(\d{2}:\d{2})\b', text)
    if len(set(receipt_times)) == 1:
        result['time'] = receipt_times[0]
    if len(lines) >= 2 and re.fullmatch(r'\d{5}\s+.+', lines[1]):
        result['branch'] = lines[0] + ', ' + lines[1]
    transaction = re.findall(r'^TSE Transaktionsnummer:\s*(\d+)\s*$', text, re.M)
    registers = re.findall(r'^Seriennr\. Kasse:\s*(\S+)\s*$', text, re.M)
    if len(transaction) == 1:
        result['tse_transaction'] = transaction[0]
    if len(registers) == 1:
        result['register'] = registers[0]
    for index, line in enumerate(lines):
        match = re.fullmatch(r'Seriennr\. TSE:\s*(\S+)', line)
        if match:
            serial = match[1]
            for following in lines[index+1:]:
                if not re.fullmatch(r'[A-Za-z0-9+/=]+', following):
                    break
                serial += following
            result['tse_serial'] = serial
            break
    header = next((i for i,line in enumerate(lines) if line == 'EUR'), None)
    end = next((i for i,line in enumerate(lines) if re.fullmatch(r'zu zahlen\s+' + MONEY, line, re.I)), None)
    if header is not None and end is not None and end > header:
        for line in lines[header+1:end]:
            if re.fullmatch(r'[-=_\s]+', line):
                continue
            multiple = re.fullmatch(r'(.+?)\s+(' + MONEY + r')\s+x\s+(\d+)\s+(' + MONEY + r')\s+([A-Z])', line)
            single = re.fullmatch(r'(.+?)\s+(' + MONEY + r')\s+([A-Z])', line)
            discount = re.fullmatch(r'(Preisvorteil|Lidl Plus Rabatt)\s+(' + MONEY + r')', line)
            item = dict(description=None,quantity=None,unit=None,unit_price_cents=None,amount_cents=None,
                        tax_code=None,kind='item',raw_line=line)
            if multiple:
                item.update(description=multiple[1],unit_price_cents=cents(multiple[2]),quantity=multiple[3],
                            unit='piece',amount_cents=cents(multiple[4]),tax_code=multiple[5])
                if item['unit_price_cents'] * int(item['quantity']) != item['amount_cents']:
                    result['warnings'].append('item_quantity_price_mismatch')
            elif single:
                item.update(description=single[1],amount_cents=cents(single[2]),tax_code=single[3])
            elif discount:
                item.update(description=discount[1],amount_cents=cents(discount[2]),kind='discount')
            else:
                result['warnings'].append('unparsed_item_line')
                result['unparsed_lines'].append(line)
                continue
            if 'pfand' in item['description'].casefold():
                item['kind'] = 'deposit'
            elif item['amount_cents'] < 0 and item['kind'] == 'item':
                item['kind'] = 'refund'
            result['items'].append(item)
        if result['total_cents'] is not None and sum(item['amount_cents'] for item in result['items']) != result['total_cents']:
            result['warnings'].append('item_sum_mismatch')
    else:
        result['warnings'].append('item_layout_not_recognized')
    for line in lines:
        tax = re.fullmatch(r'([A-Z])\s+(\d+(?:,\d+)?)\s*%\s+(' + MONEY + r')\s+(' + MONEY + r')\s+(' + MONEY + r')', line)
        if tax:
            row = dict(code=tax[1],rate=tax[2].replace(',','.'),tax_cents=cents(tax[3]),net_cents=cents(tax[4]),gross_cents=cents(tax[5]))
            result['taxes'].append(row)
            if row['tax_cents'] + row['net_cents'] != row['gross_cents']:
                result['warnings'].append('tax_sum_mismatch')
    if result['taxes'] and result['total_cents'] is not None and sum(row['gross_cents'] for row in result['taxes']) != result['total_cents']:
        result['warnings'].append('tax_total_mismatch')
    result['warnings'] = sorted(set(result['warnings']))
    return result
