import argparse
import json
import os
import sys
from uuid import uuid4
from .doctor import doctor
from .session import ROOT, capabilities, load_config, session
from .retailers import RETAILERS


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="python -m receiptbot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Lokale Umgebung lesend prüfen")
    commands.add_parser('retailers', help='Implementierungsstand aller Händler ohne Gerätezugriff')
    discovery = commands.add_parser('discover-apps', help='Installierte Händler-App-Metadaten gezielt lokal ermitteln; kein UI-Zugriff')
    discovery.add_argument('--app', choices=tuple(RETAILERS), required=True)
    discovery.add_argument('--apply', action='store_true', help='Nur eindeutige beobachtete Bundle-ID lokal übernehmen')
    ready = commands.add_parser('ready', help='Lokale Startvoraussetzungen prüfen und optional auf USB/Entsperrung warten')
    ready.add_argument('--wait', type=int, default=0, metavar='SEKUNDEN')
    inspect = commands.add_parser("inspect", help="App aktivieren; UI ausschließlich lokal speichern")
    inspect.add_argument("--app", choices=("kaufland", "dm", "lidl", "rossmann"), required=True)
    inspect.add_argument("--dry-run", action="store_true", help="Nur Konfiguration prüfen, ohne Session oder UI-Lesen")
    export = commands.add_parser("export", help="Kaufland über Share Sheet/iCloud oder AirDrop exportieren")
    export.add_argument("--app", choices=("kaufland", "dm", "lidl", "rossmann"), required=True)
    export.add_argument("--limit", type=int, default=1)
    export.add_argument("--new-only", action="store_true")
    export.add_argument("--dry-run", action="store_true")
    export.add_argument("--transport", choices=('airdrop', 'icloud'), help='Überschreibt lokale Transportwahl')
    export.add_argument("--all", dest="all_receipts", action="store_true")
    export.add_argument('--resume', action='store_true', help='Mit --all/--since aktuelle Listenposition fortsetzen; kein neuer Scan vom Anfang')
    from datetime import date
    export.add_argument('--since', type=date.fromisoformat, help='Nur Bons ab YYYY-MM-DD einschließlich exportieren')
    export.add_argument("--approve-large-run", action="store_true", help="Explizite Freigabe für großen Lauf nach drei Gerätetests")
    export.add_argument("--max-pages", type=int, default=100)
    export.add_argument("--receive-timeout", type=int, default=90)
    export.add_argument("--abandon-pending", action="store_true", help="Bewusst alten unklaren Transfer aufgeben; danach neu versuchen")
    commands.add_parser("parse", help="Verifizierte Originale lokal auslesen")
    commands.add_parser("report", help="CSV-Tabellen, Buchungsjournal und Monatssummen lokal erzeugen")
    commands.add_parser("bookings", help="Gemeinsames buchungen.csv aus allen verifizierten Bons aktualisieren (ohne iPhone)")
    archive = commands.add_parser('archive-file', help='Lokale Bytes prüfen/ablegen; kein Original- oder Exportnachweis')
    archive.add_argument('file')
    archive.add_argument('--app', required=True, choices=('kaufland', 'dm', 'lidl', 'rossmann'))
    archive.add_argument('--expected-sha256', required=True)
    archive.add_argument('--expected-size', required=True, type=int)
    archive.add_argument('--receipt-id')
    archive.add_argument('--date', help='Belegtes Einkaufsdatum YYYY-MM-DD; darf fehlen')
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == 'retailers':
            for spec in RETAILERS.values():
                print(spec.name + ': ' + (('Adapter/Parser implementiert; iCloud-Export am Referenzgerät geprüft.' if spec.device_export_verified
                    else 'Adapter/Parser implementiert; automatischer Gerätetest offen.')
                    if spec.adapter_implemented and spec.parser_implemented else 'vorbereitet; Adapter/Parser nicht implementiert, Export gesperrt.'))
            return 0
        if args.command == 'discover-apps':
            from .discovery import discover_apps
            return discover_apps(args.app, args.apply)
        if args.command == 'ready':
            from .readiness import ready
            return ready(load_config(), args.wait)
        if args.command == 'archive-file':
            from .archive import Archive
            result = Archive(ROOT / 'data').receive(args.file, args.app,
                args.expected_sha256, args.expected_size, args.receipt_id, args.date)
            print('Dateikopie bytegetreu bestätigt; ' + ('bereits abgelegt.' if result['already_stored'] else 'lokal abgelegt.'))
            print('Originalquelle, Belegzuordnung und Formatlesbarkeit noch nicht verifiziert; kein erfolgreicher Händlerexport.')
            return 0
        if args.command in ("parse", "report", "bookings"):
            from .reporting import parse_all, report
            if args.command == 'parse':
                count = parse_all(ROOT / 'data', ROOT / 'output')
                print(f'{count} verifizierte Originale verarbeitet. Abgeleitete Daten unter output/processed/.')
            else:
                count, items = report(ROOT / 'data', ROOT / 'output')
                print(f'{count} verifizierte Belege, {items} erkannte Positionszeilen. Buchungsjournal: output/reports/buchungen.csv')
            return 0
        if args.command == "export":
            if not 1 <= args.limit <= 10000 or (args.limit > 3 or args.all_receipts) and not args.approve_large_run:
                raise ValueError("Ohne ausdrückliche Großlauf-Freigabe sind nur Limits von 1 bis 3 zulässig.")
            if args.dry_run:
                print("Trockenlauf: keine Gerätesession, keine Navigation, kein Export, keine Statusänderung.")
                spec = RETAILERS[args.app]
                print(('Adapter/Parser implementiert; Referenzgerät geprüft.' if spec.device_export_verified else 'Adapter/Parser implementiert; vollständiger Gerätetest noch offen.')
                      if spec.adapter_implemented else 'Händleradapter noch nicht implementiert.')
                return 0
            from .workflow import export_receipts
            return export_receipts(load_config(), args.app, args.limit, args.new_only, args.all_receipts,
                args.approve_large_run, args.receive_timeout, args.max_pages, args.abandon_pending, args.transport, args.resume, args.since)
        config = load_config()
        capabilities(config, args.app)
        if args.dry_run:
            print("Konfiguration geprüft; keine Session, kein UI-Zugriff und kein Export. Gerätetest weiterhin offen.")
            return 0
        # Sensitive Inhalte werden weder ausgegeben noch an Dienste gesendet.
        with session(config, args.app) as driver:
            xml = driver.page_source
            directory = ROOT / "data/debug"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = directory / f"{args.app}-{uuid4().hex}.xml"
            with target.open("x") as handle:
                handle.write(xml)
        print("Session und UI-Abfrage erfolgreich. Sensibler UI-Dump nur lokal unter data/debug gespeichert.")
        print("Vor Modellprüfung dieses Inhalts ist deine ausdrückliche Freigabe erforderlich.")
        return 0
    except KeyboardInterrupt:
        print("Abgebrochen.", file=sys.stderr)
        return 130
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        # Nur selbst erzeugte Validierungsfehler ausgeben; Pfade/Dateiinhalte nie dumpen.
        if type(exc) is ValueError:
            print(str(exc), file=sys.stderr)
        else:
            print("Lokaler Datei-/Konfigurationsfehler; Inhalt wird aus Datenschutzgründen nicht ausgegeben.", file=sys.stderr)
        return 2
    except Exception:
        print("Befehl fehlgeschlagen. Keine Rohfehlermeldung ausgegeben; lokalen Zustand prüfen.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
