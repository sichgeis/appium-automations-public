from copy import deepcopy
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from receiptbot.household import build_catalog, migrate, source_id, product_name

CATALOG = 'catalog-00000000-0000-4000-8000-000000000001'


def item(position, name='Nussschokolade 100 g', amount=199, **extra):
    return dict(position=position, description=name, amount_cents=amount, kind='item', category='Lebensmittel',
                subcategory='Süßigkeiten', quantity=None, unit=None, unit_price_cents=None, **extra)


def receipt(items, **extra):
    return dict(merchant='kaufland', sha256='a' * 64, date='2026-07-01', currency='EUR', items=items, **extra)


class HouseholdTests(unittest.TestCase):
    def test_image_enrichment_preserves_identity_and_money(self):
        records = [receipt([item(1)])]; old = build_catalog(records, CATALOG)[0]
        image = {'id': '1' * 32, 'mime': 'image/jpeg', 'title': 'Synthetisches Bild', 'kind': 'illustrative', 'sourceUrl': 'https://example.org/source'}
        updated = build_catalog(records, CATALOG, {'images': {old['products'][0]['id']: image}})[0]
        self.assertEqual(updated['products'][0].pop('image'), image)
        self.assertEqual(updated['products'], old['products'])
        self.assertEqual(updated['ledgerTotals'], old['ledgerTotals'])

    def test_optional_private_people_do_not_change_product_ids(self):
        records = [receipt([item(1)])]
        old = build_catalog(records, CATALOG)[0]
        people = {'a': 'Test rechts', 'b': 'Test links', 'version': 1}
        updated = build_catalog(records, CATALOG, {'people': people})[0]
        self.assertEqual(updated['people'], people)
        self.assertEqual(old['products'], updated['products'])
        self.assertNotEqual(old['revision'], updated['revision'])
        with self.assertRaises(ValueError): build_catalog(records, CATALOG, {'people': {'a': '', 'b': 'Test', 'version': 1}})

    def test_generic_short_text_stays_separate_and_opaque_ids_are_stable(self):
        record = receipt([item(1, name='SCHOKOLADE'), item(2, name='SCHOKOLADE')])
        catalog, lineage, candidates = build_catalog([record], CATALOG)
        self.assertEqual(len(catalog['products']), 2)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(catalog, build_catalog([record], CATALOG)[0])
        self.assertEqual(len(lineage), 2)
        self.assertNotIn('sha256', json.dumps(catalog))

    def test_only_confirmed_same_variant_can_be_grouped(self):
        record = receipt([item(1), item(2)])
        rules = {'groups': [dict(id='confirmed-test', confirmed=True, evidence='Synthetisch geprüfte Marke, Sorte und Größe',
                                members=[source_id(record, i) for i in record['items']])]}
        catalog = build_catalog([record], CATALOG, rules)[0]
        self.assertEqual((len(catalog['products']), catalog['products'][0]['count'], catalog['products'][0]['total']), (1, 1, 398))
        for name in ['Joghurt-Erdbeer-Schokolade 100 g']:
            bad = deepcopy(record); bad['items'][1]['description'] = name
            with self.assertRaises(ValueError): build_catalog([bad], CATALOG, rules)
        rules['groups'][0]['confirmed'] = False
        with self.assertRaises(ValueError): build_catalog([record], CATALOG, rules)

    def test_same_variant_different_sizes_and_prices_share_one_card_with_range(self):
        record = receipt([item(1, name='Nussschokolade 100 g', amount=199), item(2, name='Nussschokolade 200 g', amount=349), item(3, name='Joghurt-Erdbeer-Schokolade 100 g', amount=149)])
        catalog = build_catalog([record], CATALOG)[0]
        self.assertEqual(len(catalog['products']), 2)
        nuts = next(p for p in catalog['products'] if p['name'] == 'Nussschokolade')
        self.assertEqual((nuts['low'], nuts['high'], nuts['total']), (199, 349, 548))

    def test_normalization_preserves_flavor_and_fat_but_ignores_package_sizes(self):
        self.assertEqual(product_name('Test. Wasser 6x0,5 l'), product_name('Test. Wasser 1,5 l'))
        self.assertEqual(product_name('Test. Wasser 1,5 l'), product_name('Test.Wasser 500ml'))
        self.assertNotEqual(product_name('Testmilch 1,5% 1l'), product_name('Testmilch 3,5% 1l'))
        self.assertNotEqual(product_name('Nussschokolade 100g'), product_name('Erdbeer-Joghurt-Schokolade 100g'))

    def test_direct_discount_once_and_other_money_separate(self):
        rows = [item(1, amount=400), dict(position=2, description='Produktrabatt', amount_cents=-50, kind='discount', category='Lebensmittel', related_position=1),
                dict(position=3, description='Bonrabatt', amount_cents=-20, kind='discount', category='Nicht zugeordnete Rabatte'),
                dict(position=4, description='Pfand', amount_cents=25, kind='deposit', category='Pfand'),
                dict(position=5, description='Seife', amount_cents=200, kind='item', category='Haushalt')]
        catalog = build_catalog([receipt(rows)], CATALOG)[0]
        self.assertEqual(catalog['products'][0]['total'], 350)
        self.assertEqual(catalog['products'][0]['quantity'], 'Menge nicht vollständig belegt')
        self.assertEqual(catalog['ledgerTotals'], {'deposit': 25, 'discount': -20, 'food': 400, 'food_discount': -50, 'other': 200})

    def test_only_selected_retailers_and_date_range(self):
        records = [receipt([item(1)]), receipt([item(1)])]
        records[1]['merchant'] = 'dm'
        older = deepcopy(records[0]); older['date'] = '2026-05-31'
        catalog = build_catalog(records + [older], CATALOG)[0]
        self.assertEqual(catalog['coverage']['receipts'], 1)
        with self.assertRaises(ValueError): build_catalog([records[0], records[0]], CATALOG)

    def test_new_purchases_do_not_rename_existing_cards(self):
        old = receipt([item(1)])
        new = deepcopy(old); new['sha256'] = 'b' * 64
        first = build_catalog([old], CATALOG)[0]
        updated = build_catalog([old, new], CATALOG)[0]
        self.assertIn(first['products'][0]['id'], {p['id'] for p in updated['products']})
        self.assertEqual(len(updated['products']), 1)
        self.assertNotEqual(first['revision'], updated['revision'])

    def test_migration_checks_originals_before_writing_and_keeps_private_lineage_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'output/llm_review').mkdir(parents=True); (root/'data').mkdir()
            original = root/'original.pdf'; original.write_bytes(b'synthetic original')
            evidence = root/'evidence.png'; evidence.write_bytes(b'synthetic evidence')
            record = receipt([item(1)], total_cents=199, fiscal_total_cents=199, cash_outflow_cents=199,
                             printed_cash_outflow_cents=199, payment_offsets=[], taxes=[], visual_reviewed=True,
                             source=str(original), original_size=original.stat().st_size,
                             visual_evidence=[dict(path=str(evidence), sha256=sha256(evidence.read_bytes()).hexdigest())])
            record['sha256'] = sha256(original.read_bytes()).hexdigest()
            (root/'output/llm_review/reviewed_receipts.json').write_text(json.dumps([record]))
            with closing(sqlite3.connect(root/'data/exports.sqlite3')) as db:
                db.execute('CREATE TABLE originals (merchant TEXT, sha256 TEXT, byte_count INTEGER)')
                db.execute('INSERT INTO originals VALUES (?,?,?)', (record['merchant'], record['sha256'], record['original_size']))
                db.commit()
            destination = root/'output/household'
            self.assertEqual(migrate(root, destination)['cards'], 1)
            catalog = (destination/'catalog.json').read_bytes()
            self.assertNotIn(str(root), catalog.decode())
            original.write_bytes(b'changed')
            with self.assertRaises(ValueError): migrate(root, destination)
            self.assertEqual((destination/'catalog.json').read_bytes(), catalog)
