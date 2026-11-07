"""Lokale technische Migration geprüfter Bonpositionen in einen privaten Katalog.

Kein Gerät/Netzwerk/LLM. Gleiche Händlerbezeichnung/Sorte wird zunächst zusammengefasst;
Packungsgrößen und Preise sind nach Nutzerentscheidung keine Gruppengrenze.
Generische unklare Bezeichnungen bleiben getrennt.
"""
from collections import defaultdict, Counter
from contextlib import closing
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import sqlite3
from uuid import uuid4

from .reporting import atomic_write
from .semantic_review import validate_review

FOOD = {'Lebensmittel', 'Getränke'}
SINCE = '2026-06-01'
GENERIC = {'schokolade', 'schoko', 'joghurt', 'yoghurt', 'artikel', 'lebensmittel', 'obst', 'gemüse', 'diverse', 'milka schokolade', 'klc schokolade'}


def display_name(value):
    value = re.sub(r'(?:\d+\s*[x×]\s*)?\d+(?:[.,]\d+)?\s*(?:kg|ml|cl|g|l|stk?|stück)\b\.?', '', value, flags=re.I)
    value = re.sub(r'\s+(?:kg|st\.?)\s*$', '', value, flags=re.I)
    return re.sub(r'\s+', ' ', value).strip(' .,:;-')


def product_name(value):
    return re.sub(r'\s+', ' ', re.sub(r'(?<=[^\d])\.(?=[^\d])', ' ', display_name(value))).casefold().strip()


def opaque(value):
    return 'p-' + sha256(value.encode()).hexdigest()[:24]


def source_id(receipt, item):
    return opaque(f"{receipt['merchant']}:{receipt['sha256']}:{item['position']}")


def build_catalog(receipts, catalog_id, rules=None):
    """Pure transformation; callers validate original hashes before invoking."""
    if not re.fullmatch(r'catalog-[0-9a-f-]{36}', catalog_id):
        raise ValueError('Ungültige Katalogkennung.')
    purchases, ledger, lineage = {}, [], {}
    counts = Counter()
    for receipt in receipts:
        if receipt['merchant'] not in ('kaufland', 'lidl'):
            continue
        if date.fromisoformat(receipt['date']) < date.fromisoformat(SINCE):
            continue
        if receipt.get('currency') != 'EUR':
            raise ValueError('Nicht unterstützte Währung.')
        counts['receipts'] += 1
        for item in receipt['items']:
            pid = source_id(receipt, item)
            if pid in lineage:
                raise ValueError('Doppelte Kaufposition.')
            lineage[pid] = {'merchant': receipt['merchant'], 'sha256': receipt['sha256'], 'position': item['position']}
            kind, category = item['kind'], item['category']
            row = {'id': pid, 'kind': kind, 'amount_cents': item['amount_cents'], 'category': category}
            if kind == 'item' and category in FOOD:
                if item['amount_cents'] < 0:
                    raise ValueError('Negative Artikelposition benötigt Prüfung.')
                purchases[pid] = {
                    'id': pid, 'receipt': opaque(receipt['merchant'] + ':' + receipt['sha256']),
                    'merchant': receipt['merchant'], 'month': receipt['date'][:7],
                    'name': item['description'], 'category': category, 'subcategory': item.get('subcategory', ''),
                    'gross': item['amount_cents'], 'amount': item['amount_cents'],
                    'quantity': item.get('quantity'), 'unit': item.get('unit'),
                    'unitPrice': item.get('unit_price_cents'),
                    'review': item.get('review_status', ''),
                }
                row['bucket'] = 'food'
            elif kind == 'deposit': row['bucket'] = 'deposit'
            elif kind == 'refund': row['bucket'] = 'refund'
            elif kind == 'discount':
                related = item.get('related_position')
                parent = source_id(receipt, {'position': related}) if type(related) is int else None
                row.update(bucket='discount', parent=parent)
            else: row['bucket'] = 'other'
            ledger.append(row)
    for row in ledger:
        if row['bucket'] == 'discount' and row['parent'] in purchases:
            purchases[row['parent']]['amount'] += row['amount_cents']
            row['bucket'] = 'food_discount'
    if any(p['amount'] < 0 for p in purchases.values()):
        raise ValueError('Rabatt übersteigt zugeordneten Artikelbetrag.')

    memberships, confirmed = {}, {}
    for rule in (rules or {}).get('groups', []):
        members = rule.get('members', [])
        if rule.get('confirmed') is not True or not rule.get('evidence') or not members:
            raise ValueError('Produktidentität muss ausdrücklich bestätigt sein.')
        if not re.fullmatch(r'[a-zA-Z0-9-]{1,80}', rule.get('id', '')):
            raise ValueError('Ungültige Produktregel.')
        if any(pid not in purchases or pid in memberships for pid in members) or len(set(members)) != len(members):
            raise ValueError('Fehlende oder mehrfach zugeordnete Kaufposition.')
        identity = {(purchases[pid]['merchant'], product_name(purchases[pid]['name']), purchases[pid]['subcategory']) for pid in members}
        if len(identity) != 1:
            raise ValueError('Abweichende Händler/Sorten dürfen nicht still zusammengeführt werden.')
        group = opaque('confirmed:' + rule['id'])
        if group in confirmed: raise ValueError('Doppelte Gruppenkennung.')
        confirmed[group] = rule
        for pid in members: memberships[pid] = group
    groups, identities = defaultdict(list), {}
    for pid, purchase in purchases.items():
        name = product_name(purchase['name'])
        identity = (purchase['merchant'], name, purchase['subcategory'])
        group = memberships.get(pid) or (pid if not name or name in GENERIC else opaque('named-product:' + json.dumps(identity, ensure_ascii=False)))
        if group in identities and identities[group] != identity:
            raise ValueError('Kollision verschiedener Produktidentitäten.')
        identities[group] = identity
        groups[group].append(purchase)
    # Explicit consumption rules may cross brands/organic labels, never fuzzy-name matching.
    original_ids = list(groups)
    targets = {gid: gid for gid in original_ids}
    used, consumption = set(), {}
    for rule in (rules or {}).get('consumption_groups', []):
        members = rule.get('members', [])
        if (not re.fullmatch(r'[a-z0-9-]{1,80}', rule.get('key', ''))
                or not members or len(members) != len(set(members))
                or not rule.get('evidence') or not isinstance(rule.get('name'), str) or not rule['name'].strip()
                or not isinstance(rule.get('detail'), str)):
            raise ValueError('Unvollständige Verbrauchsgruppenregel.')
        if any(gid not in groups or gid in used for gid in members):
            raise ValueError('Fehlende oder mehrfach zugeordnete Produktkarte.')
        gid = opaque('consumption-group:' + rule['key'])
        if gid in groups or gid in consumption:
            raise ValueError('Doppelte Verbrauchsgruppenkennung.')
        entries = [p for member in members for p in groups[member]]
        if len({p['category'] for p in entries}) != 1:
            raise ValueError('Warenkategorien dürfen nicht still zusammengeführt werden.')
        for member in members:
            used.add(member)
            targets[member] = gid
        consumption[gid] = rule
        groups[gid] = entries
    for member in used:
        del groups[member]
    renames = (rules or {}).get('renames', {})
    if any(gid not in groups for gid in renames):
        raise ValueError('Anzeigenamensregel ohne Produktkarte.')
    for rule in renames.values():
        if not isinstance(rule.get('name'), str) or not rule['name'].strip() or not rule.get('evidence'):
            raise ValueError('Anzeigename benötigt nachvollziehbaren Kontext.')
    cards = []
    for gid, entries in groups.items():
        first = entries[0]
        prices = [p['unitPrice'] for p in entries if p['unitPrice'] is not None]
        units = {p['unit'] for p in entries if p['quantity'] is not None}
        comparable_prices = len(prices) == len(entries) and len({p['unit'] for p in entries}) == 1
        if not comparable_prices: prices = [p['amount'] for p in entries]
        quantities = defaultdict(Decimal)
        known = 0
        for p in entries:
            if p['quantity'] is not None and p['unit']:
                quantities[p['unit']] += Decimal(str(p['quantity']))
                known += 1
        parts = [f"{format(amount, 'f').replace('.', ',')} {'Stück' if unit == 'piece' else unit}" for unit, amount in sorted(quantities.items())]
        quantity = ' · '.join(parts) + (' insgesamt' if known == len(entries) else ' · Mengen teilweise offen') if parts else 'Menge nicht vollständig belegt'
        cards.append({
            'id': gid, 'name': (consumption.get(gid) or renames.get(gid) or {}).get('name', display_name(first['name']) or first['name']), 'brand': first['category'],
            'detail': (consumption.get(gid) or renames.get(gid) or {}).get('detail', first['subcategory']),
            'merchant': ' · '.join({'kaufland': 'Kaufland', 'lidl': 'Lidl'}[m] for m in sorted({p['merchant'] for p in entries})),
            'count': len({p['receipt'] for p in entries}), 'quantity': quantity,
            'total': sum(p['amount'] for p in entries), 'low': min(prices) if prices else None,
            'high': max(prices) if prices else None, 'priceLabel': 'Einzelpreis laut Bon' if comparable_prices else 'Betrag pro Bonposition',
            'variant': 'Marken & Bio gemeinsam' if gid in consumption else 'Identität bestätigt' if gid in confirmed else 'Sorte unklar – einzeln' if product_name(first['name']) in GENERIC else 'Größen & Angebote gemeinsam',
            'purchases': [{'id': p['id'], 'amount': p['amount'], 'month': p['month']} for p in entries],
        })
    cards.sort(key=lambda p: (-p['total'], p['id']))
    images = (rules or {}).get('images', {})
    for card in cards:
        if card['id'] in images:
            card['image'] = images[card['id']]
    if len({p['id'] for p in cards}) != len(cards): raise ValueError('Kennungskollision.')
    totals = {bucket: sum(r['amount_cents'] for r in ledger if r['bucket'] == bucket)
              for bucket in sorted({r['bucket'] for r in ledger})}
    if sum(p['total'] for p in cards) != totals.get('food', 0) + totals.get('food_discount', 0):
        raise ValueError('Katalogsumme nicht nachvollziehbar.')
    payload = {'format': 'household-catalog', 'version': 1, 'id': catalog_id, 'synthetic': False,
               'products': cards, 'coverage': dict(counts), 'ledgerTotals': totals}
    if consumption:
        if (rules or {}).get('grouping_version') != 1:
            raise ValueError('Verbrauchsgruppen benötigen eine unterstützte Migrationsversion.')
        payload['regrouping'] = {'version': 1, 'sources': [{'id': gid, 'target': targets[gid]} for gid in sorted(original_ids)]}
    people = (rules or {}).get('people')
    if people is not None:
        if (not isinstance(people, dict) or set(people) != {'a', 'b', 'version'} or type(people['version']) is not int or people['version'] < 1
                or any(not isinstance(people[k], str) or not people[k].strip() or len(people[k]) > 24 for k in ('a', 'b'))):
            raise ValueError('Ungültige private Anzeigenamen.')
        payload['people'] = dict(people)
    payload['revision'] = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    candidates = defaultdict(list)
    for pid, p in purchases.items(): candidates[(p['merchant'], p['name'])].append(pid)
    return payload, lineage, [{'merchant': m, 'description': name, 'members': ids}
                              for (m, name), ids in sorted(candidates.items()) if len(ids) > 1]


def migrate(root, destination):
    root, destination = Path(root), Path(destination)
    records = json.loads((root / 'output/llm_review/reviewed_receipts.json').read_text())
    database = root / 'data/exports.sqlite3'
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        canonical = {(m, h): (size, h) for m, h, size in db.execute('SELECT merchant,sha256,byte_count FROM originals')}
    validate_review(records, canonical)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = destination / 'migration.json'
    if not settings.exists():
        atomic_write(settings, lambda f: json.dump({'catalog_id': 'catalog-' + str(uuid4()), 'groups': []}, f))
    rules = json.loads(settings.read_text())
    image_map = destination / 'product-images.json'
    if image_map.exists():
        rules['images'] = json.loads(image_map.read_text())['products']
    catalog, lineage, candidates = build_catalog(records, rules['catalog_id'], rules)
    for filename, value in [('catalog.json', catalog), ('lineage.json', lineage), ('identity-candidates.json', candidates)]:
        atomic_write(destination / filename, lambda f, value=value: json.dump(value, f, ensure_ascii=False, indent=2))
    validate_review(records, canonical)
    return {'receipts': catalog['coverage']['receipts'], 'purchase_lines': len([p for card in catalog['products'] for p in card['purchases']]),
            'cards': len(catalog['products']), 'candidate_groups': len(candidates), 'confirmed_groups': len(rules.get('groups', []))}


def main():
    os.umask(0o077)
    root = Path(__file__).resolve().parent.parent
    result = migrate(root, root / 'output/household-consumption/private')
    print(json.dumps(result))


if __name__ == '__main__': main()
