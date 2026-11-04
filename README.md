# appium-automations

Lokale Werkzeuge zum Archivieren eigener iPhone-Kassenbons und eine unabhängige
Web-App zur Zuordnung von Lebensmitteln im Haushalt.

Die Swipe-App ist über den separat geteilten UUID-Link erreichbar.

## Swipe-App

Zehn erfundene Produkte zum Ausprobieren auf Smartphone oder Desktop. Rechts:
hauptsächlich Person A; links: hauptsächlich Person B; hoch: gemeinsam. Namen und
Kostenanteile lassen sich lokal ändern. Sorten und Packungsgrößen haben getrennte
Karten. Unklare Produkte werden nicht automatisch zusammengefasst.

Fortschritt bleibt im Browser. Jedes Gerät hat eine eigene unabhängige Bewertung;
keine Synchronisierung. Exportdateien lassen sich herunterladen, wiederherstellen
und über das native Teilen-Menü weitergeben. Die frei zugängliche Demo enthält nur synthetische Daten. Ein gesondert freigegebener privater Katalog kann verschlüsselt auf Pages liegen; sein Schlüssel wird ausschließlich über einen privaten Startlink geteilt.

```sh
npm --prefix modules/household-consumption run dev
npm --prefix modules/household-consumption test
```

Die lokale Vorschau läuft unter http://127.0.0.1:8765/ nur auf dem jeweiligen Rechner.
Für Smartphones den HTTPS-UUID-Link verwenden. Native Dateifreigabe hängt vom Browser
und den installierten Apps ab; Download ist als Alternative verfügbar.

## Lokale Bonarchivierung

Benötigt macOS, Xcode, ein selbst verwaltetes iPhone mit Entwicklermodus, Node/npm
und Python. Geräte-/Signierungswerte ausschließlich lokal konfigurieren:

```sh
sh scripts/setup.sh
cp -n config.example.json config.local.json
.venv/bin/python -m receiptbot doctor
npm run doctor:ios
.venv/bin/python -m receiptbot export --app kaufland --limit 1 --dry-run
```

`setup.sh` verwendet standardmäßig Python 3.13; alternativ `PYTHON_BIN` setzen.
Die lokale Konfiguration enthält die eigenen Geräte- und Signierungswerte sowie
beobachtete App-Kennungen. Keine Kennungen aus fremden Installationen übernehmen.
Vor echten Exporten Gerät, Zugriff, Zeitraum und Originaltransport selbst prüfen.

Appium ist an Loopback gebunden; Gerätesperre verhindert parallele Steuerung.
Kein App-Reset, keine Neuinstallation oder automatische Dialogzustimmung.
Keine Käufe, Coupons oder Kontoaktionen. Nur eigene Bons verarbeiten.
`export` verwaltet seinen eigenen Server; keinen zweiten Inspektionsserver parallel
betreiben. Größere Läufe erst nach einem geprüften Einzeltransport durchführen.

Originale werden nach Format-, Bonzuordnungs- und Hashprüfung lokal archiviert.
Parserergebnisse können unvollständig sein; rechnerische Summengleichheit beweist
keine korrekte Artikelinterpretation. Siehe [Qualitätsgrenzen](docs/POSTMORTEM-CSV-QUALITAET.md).
`receiptbot.semantic_review` verarbeitet gespeicherte Prüfentscheidungen und ruft
selbst kein Sprachmodell auf.

## Tests und Datenschutz

```sh
.venv/bin/python -m unittest discover -s tests -q
npm --prefix modules/household-consumption test
```

Tests verwenden synthetische Daten. Geräte-, Dialog- und Originaltransport müssen
für die eigene Installation separat geprüft werden. Keine Funktionsgarantie für
unbeobachtete Händleroberflächen oder vollständige historische Abdeckung.

`config.local.json`, `data/`, `output/`, virtuelle Umgebungen und Abhängigkeiten
bleiben Git-ignoriert. Keine Bons, Screenshots, UI-Dumps, Passwörter, Gerätekennungen
oder privaten Auswertungen veröffentlichen. Lokales Speichern ist keine Zustimmung
zur Verarbeitung durch ein externes Modell.
