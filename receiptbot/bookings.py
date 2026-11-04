"""Ein gemeinsames, lokal erzeugtes Positionsjournal aller verifizierten Bons.

Rabatte sind eigenständige, vorzeichenbehaftete Buchungen. Prüfzeilen sind
keine erfundenen Artikel und dürfen nicht als erkannte Positionen gelten.
"""
import csv
from decimal import Decimal
import json

FIELDS = [
    'Haendler', 'Filiale', 'Filiale_Status', 'Datum', 'Uhrzeit', 'Monat',
    'Bon_ID', 'Bon_Schluessel', 'Kasse', 'Position', 'Buchungsart', 'Item',
    'Menge', 'Einheit', 'Einzelpreis', 'Einzelpreis_Cent',
    'Buchungsbetrag', 'Buchungsbetrag_Cent', 'Rabatt', 'Rabatt_Cent',
    'Rabatt_Zuordnung', 'Rabatt_ausgeschlossen', 'Waehrung',
    'Steuercode', 'Steuersatz_Prozent', 'Bon_Steuern_JSON',
    'Bon_Gesamtsumme', 'Bon_Gesamtsumme_Cent', 'Bon_Listensumme_Cent',
    'Bon_Positionsdifferenz_Cent', 'Zeilenstatus', 'Bon_Status', 'Pruefhinweise',
    'Originalzeile', 'Quelldatei', 'SHA256', 'Originalformat', 'Textquelle',
]
NUMERIC = {
    'Menge', 'Einzelpreis', 'Einzelpreis_Cent', 'Buchungsbetrag',
    'Buchungsbetrag_Cent', 'Rabatt', 'Rabatt_Cent', 'Steuersatz_Prozent',
    'Bon_Gesamtsumme', 'Bon_Gesamtsumme_Cent', 'Bon_Listensumme_Cent',
    'Bon_Positionsdifferenz_Cent', 'Position',
}
MERCHANTS = {'kaufland': 'Kaufland', 'dm': 'dm', 'lidl': 'Lidl Plus', 'rossmann': 'Rossmann'}


def money(value):
    return None if value is None else format(Decimal(value) / 100, '.2f').replace('.', ',')


def booking_rows(parsed):
    """Pure Ableitung ohne Gerätezugriff, kein Schätzen fehlender Metadaten."""
    items = parsed['items']
    total = parsed.get('total_cents')
    delta = None if total is None else total - sum(i['amount_cents'] for i in items)
    common = dict(
        Haendler=MERCHANTS.get(parsed['merchant'], parsed['merchant']),
        Filiale=parsed.get('branch'),
        Filiale_Status='extrahiert' if parsed.get('branch') else 'nicht_extrahiert',
        Datum=parsed.get('date'), Uhrzeit=parsed.get('time'),
        Monat=(parsed.get('date') or '')[:7], Bon_ID=parsed.get('receipt_id'),
        Bon_Schluessel=parsed['merchant'] + ':' + parsed['sha256'],
        Kasse=parsed.get('register'), Waehrung=parsed.get('currency'),
        Bon_Steuern_JSON=json.dumps(parsed.get('taxes', []), ensure_ascii=False),
        Bon_Gesamtsumme=money(total), Bon_Gesamtsumme_Cent=total,
        Bon_Listensumme_Cent=parsed.get('list_total_cents'),
        Bon_Positionsdifferenz_Cent=delta,
        Bon_Status=parsed.get('status'), Pruefhinweise=';'.join(parsed.get('warnings', [])),
        Quelldatei=parsed.get('source'), SHA256=parsed['sha256'],
        Originalformat=parsed.get('original_format'), Textquelle=parsed.get('source_method'),
    )
    rows = []
    for item in items:
        kind, amount = item['kind'], item['amount_cents']
        rates = {t['rate'] for t in parsed.get('taxes', []) if t.get('code') == item.get('tax_code')}
        rate = next(iter(rates)) if len(rates) == 1 else None
        excluded = item.get('discount_excluded')
        rows.append(dict(common,
            Buchungsart=kind, Item=item['description'], Menge=item.get('quantity'),
            Einheit=item.get('unit'), Einzelpreis=money(item.get('unit_price_cents')),
            Einzelpreis_Cent=item.get('unit_price_cents'),
            Buchungsbetrag=money(amount), Buchungsbetrag_Cent=amount,
            Rabatt=money(-amount) if kind == 'discount' else None,
            Rabatt_Cent=-amount if kind == 'discount' else None,
            Rabatt_Zuordnung='separate_Rabattbuchung_ohne_Artikelzuordnung' if kind == 'discount' else None,
            Rabatt_ausgeschlossen=None if excluded is None else ('ja' if excluded else 'nein'),
            Steuercode=item.get('tax_code'), Steuersatz_Prozent=rate,
            Originalzeile=item.get('raw_line'), Zeilenstatus='erkannte_Position',
        ))
    for line in parsed.get('unparsed_lines', []):
        rows.append(dict(common, Buchungsart='ungeklaerte_Quellzeile',
                         Originalzeile=line, Zeilenstatus='pruefen'))
    if delta:
        rows.append(dict(common, Buchungsart='Pruefdifferenz',
            Item='Nicht aufgeschluesselter Bonbetrag (kein erkannter Artikel)',
            Buchungsbetrag=money(delta), Buchungsbetrag_Cent=delta, Zeilenstatus='pruefen'))
    elif not rows:
        # Auch einen Bon ohne lesbare Positionen/Summe sichtbar behalten.
        rows.append(dict(common, Buchungsart='Bon_ohne_Positionen', Zeilenstatus='pruefen'))
    for number, row in enumerate(rows, 1):
        row['Position'] = number
    return rows


def write_bookings(path, rows):
    from .reporting import atomic_write, csv_cell
    rows = sorted(rows, key=lambda r: (r.get('Datum') or '', r['Haendler'], r['Bon_Schluessel'], r['Position']))

    def write(handle):
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter=';', extrasaction='raise')
        writer.writeheader()
        for row in rows:
            safe = {}
            for key, value in row.items():
                if key in NUMERIC and value is not None:
                    # Nur validierte Zahlen dürfen ohne Formel-Escaping passieren.
                    numeric = Decimal(str(value).replace(',', '.'))
                    if not numeric.is_finite():
                        raise ValueError('Nicht endlicher Zahlenwert im Buchungsjournal.')
                    safe[key] = str(value).replace('.', ',')
                else:
                    safe[key] = csv_cell(value)
            writer.writerow(safe)
    atomic_write(path, write, encoding='utf-8-sig')
