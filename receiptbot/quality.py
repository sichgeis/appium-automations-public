"""Lesendes CSV-Audit: keine Neuauswertung, Reparatur oder Originaländerung.

Zählt strukturelle Auffälligkeiten, keine statistisch gemessene Parsergenauigkeit.
Datensatznummern zählen logische CSV-Datensätze inklusive Kopf (nicht Textzeilen).
"""
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
import re
from .reporting import atomic_write, write_csv


def flags(row):
    issues = []
    if row['Zeilenstatus'] == 'erkannte_Position':
        name = row['Item'].strip()
        if not name:
            issues.append('recognized_name_missing')
        elif not re.search(r'[^\W\d_]', name, re.UNICODE):
            issues.append('recognized_name_without_letters')
        if re.fullmatch(r'(?:Zwischensumme|Subtotal|Summe|Gesamtsumme)(?:\s+(?:EUR|€))?', name, re.I):
            issues.append('summary_classified_as_position')
    if row['Buchungsart'] == 'ungeklaerte_Quellzeile':
        issues.append('unparsed_source_line')
    if row['Buchungsart'] == 'Pruefdifferenz':
        issues.append('artificial_reconciliation_row')
    return issues


def audit_rows(rows):
    by_merchant = defaultdict(list)
    findings = []
    for record, row in enumerate(rows, 2):
        by_merchant[row['Haendler']].append(row)
        for flag in flags(row):
            findings.append(dict(Datensatz=record, Haendler=row['Haendler'],
                Bon_Schluessel=row['Bon_Schluessel'], Position=row['Position'], Befund=flag))
    merchants = {}
    for merchant, group in sorted(by_merchant.items()):
        receipts = defaultdict(list)
        for row in group:
            receipts[row['Bon_Schluessel']].append(row)
        recognized = [r for r in group if r['Zeilenstatus'] == 'erkannte_Position']
        receipt_flags = Counter()
        for receipt in receipts.values():
            for flag in set(f for r in receipt for f in flags(r)):
                receipt_flags[flag] += 1
        amounts_match = raw_amounts_match = 0
        for receipt in receipts.values():
            totals = {r['Bon_Gesamtsumme_Cent'] for r in receipt}
            if len(totals) != 1 or not next(iter(totals)):
                continue
            total = int(next(iter(totals)))
            amounts_match += sum(int(r['Buchungsbetrag_Cent'] or 0) for r in receipt) == total
            raw_amounts_match += sum(int(r['Buchungsbetrag_Cent'] or 0) for r in receipt
                                    if r['Zeilenstatus'] == 'erkannte_Position') == total
        merchants[merchant] = dict(
            receipts=len(receipts), rows=len(group), recognized_rows=len(recognized),
            row_types=dict(Counter(r['Buchungsart'] for r in group)),
            issue_rows=dict(Counter(f for r in group for f in flags(r))),
            issue_receipts=dict(receipt_flags),
            review_receipts=sum(any(r['Bon_Status'] == 'review_required' for r in receipt) for receipt in receipts.values()),
            branch_missing_receipts=sum(not receipt[0]['Filiale'] for receipt in receipts.values()),
            recognized_quantity_missing=sum(not r['Menge'] for r in recognized),
            recognized_unit_price_missing=sum(not r['Einzelpreis'] for r in recognized),
            totals_match_including_artificial_rows=amounts_match,
            recognized_totals_match_without_artificial_rows=raw_amounts_match,
        )
    return dict(rows=len(rows), merchants=merchants,
                limits='Strukturaudit, keine vollstaendige manuelle Artikelpruefung. Summengleichheit beweist keine korrekte Zuordnung.'), findings


def audit_file(source, destination):
    source, destination = Path(source), Path(destination)
    raw = source.read_bytes()
    with source.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle, delimiter=';'))
    summary, findings = audit_rows(rows)
    summary.update(source_sha256=sha256(raw).hexdigest(), source_bytes=len(raw))
    atomic_write(destination / 'summary.json', lambda h: json.dump(summary, h, ensure_ascii=False, indent=2))
    write_csv(destination / 'findings.csv', ['Datensatz', 'Haendler', 'Bon_Schluessel', 'Position', 'Befund'], findings)
    if source.read_bytes() != raw:
        raise ValueError('CSV wurde waehrend des lesenden Audits geaendert; Audit wiederholen.')
    return summary


def main():
    from .session import ROOT
    result = audit_file(ROOT / 'output/reports/buchungen.csv', ROOT / 'output/quality')
    print(json.dumps(dict(rows=result['rows'], merchants=result['merchants']), ensure_ascii=False))


if __name__ == '__main__':
    main()
