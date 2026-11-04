from copy import deepcopy
from hashlib import sha256
import csv
import json
from pathlib import Path
import tempfile
import unittest
from receiptbot.semantic_review import kaufland_candidates, enrich_payments, validate_review, write_table
from synthetic import TEXT,pdf
from receiptbot.archive import file_digest


class SemanticReviewTests(unittest.TestCase):
    def test_split_names_and_subtotal_are_not_extra_items(self):
        text=TEXT.replace('Testmilch 2 * 1,50 3,00 B','Testmilch\n2 * 1,50 3,00 B').replace('Summe 3,80','Zwischensumme 4,00\nSumme 3,80')
        items,notes=kaufland_candidates(text)
        self.assertEqual(len(items),3)
        self.assertEqual(items[0]['description'],'Testmilch')
        self.assertEqual(items[0]['quantity'],'2')
        self.assertEqual(len(items[0]['source_lines']),2)
        self.assertEqual(sum(i['amount_cents'] for i in items),380)
        self.assertTrue(any(n['type']=='subtotal' for n in notes))

    def test_missing_name_is_not_accepted(self):
        with self.assertRaises(ValueError):kaufland_candidates('Kaufland\nPreis EUR\n2 * 1,50 3,00 B\nSumme 3,00')

    def test_partner_discount_after_fiscal_total_changes_spend_not_tax_base(self):
        receipt=dict(merchant='dm',total_cents=1000,items=[dict(amount_cents=1000)])
        text='SUMME EUR 10,00\nPartner-Rabatte auf rabattfähige Artikel\nCoupon TEST -2,00\nZu zahlender Betrag EUR 8,00'
        enrich_payments(receipt,text)
        self.assertEqual((receipt['fiscal_total_cents'],receipt['total_cents'],receipt['cash_outflow_cents']),(1000,800,800))
        self.assertEqual(receipt['items'][-1]['scope'],'partner_discount_after_fiscal_total')
        self.assertEqual(receipt['difference_cents'],0)

    def test_gift_card_is_payment_method_not_a_second_discount(self):
        receipt=dict(merchant='kaufland',total_cents=1000,items=[dict(amount_cents=1000)])
        enrich_payments(receipt,'Summe 10,00\nCoupon 1,00\nGutschein 5,00\nKartenzahlung 4,00\nSteuer')
        self.assertEqual((len(receipt['items']),receipt['total_cents'],receipt['cash_outflow_cents']),(1,1000,400))

    def fixture(self,root):
        source=pdf(root/'original.pdf')
        image=root/'visual-evidence.png';image.write_bytes(b'synthetic review evidence')
        items,_=kaufland_candidates(TEXT)
        for n,item in enumerate(items,1):item.update(position=n,category='Test')
        size,digest=file_digest(source)
        return dict(merchant='kaufland',sha256=digest,source=str(source),original_size=size,
                    visual_reviewed=True,visual_evidence=[dict(path=str(image),sha256=sha256(image.read_bytes()).hexdigest())],
                    items=items,total_cents=380,fiscal_total_cents=380,cash_outflow_cents=380,
                    printed_cash_outflow_cents=380,payment_offsets=[],taxes=[])

    def test_real_cent_controls_duplicates_evidence_and_original_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=self.fixture(Path(tmp));validate_review([p])
            for key,value in [('printed_cash_outflow_cents',379),('total_cents',381),('visual_reviewed',False)]:
                bad=deepcopy(p);bad[key]=value
                with self.subTest(key=key),self.assertRaises(ValueError):validate_review([bad])
            with self.assertRaises(ValueError):validate_review([p,p])
            with self.assertRaises(ValueError):validate_review([p],{})
            bad=deepcopy(p);bad['items'][0]['quantity']='3'
            with self.assertRaises(ValueError):validate_review([bad])
            bad=deepcopy(p);bad['items'][0]['description']='Zwischensumme'
            with self.assertRaises(ValueError):validate_review([bad])
            Path(p['source']).write_bytes(b'changed')
            with self.assertRaises(ValueError):validate_review([p])

    def test_csv_keeps_negative_money_numeric_and_text_formula_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.csv'
            write_table(p,[dict(Item='=unsafe;\nText',Buchungsbetrag='-1,25',Buchungsbetrag_Cent=-125)])
            with p.open(encoding='utf-8-sig',newline='') as f:row=next(csv.DictReader(f,delimiter=';'))
            self.assertEqual(row['Buchungsbetrag'],'-1,25')
            self.assertEqual(row['Buchungsbetrag_Cent'],'-125')
            self.assertTrue(row['Item'].startswith("'="))
