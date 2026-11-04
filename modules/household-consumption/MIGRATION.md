# Technische Katalogmigration

Kein sichtbarer Produktimport. Ein privater Startlink wählt den Katalog; Browser
lädt und entschlüsselt automatisch. Öffentlicher Demo-Code und echte Daten bleiben
getrennt. Bewertungen bleiben unabhängig pro Gerät.

## Lokale Aufbereitung

`.venv/bin/python -m receiptbot.household` liest die vorhandenen strukturierten
Prüfentscheidungen und die Archivdatenbank nur lesend. Original-/Prüfbildhashes und
Centkontrollen werden davor und danach überprüft. Kein Gerät, Netzwerk oder neuer
Modellaufruf. Es werden nur die ausgewählten Händler und der festgelegte Zeitraum
berücksichtigt. Originale, Prüfentscheidungen und Archivstatus bleiben unverändert.

Unter `output/household-consumption/private/` entstehen:

- `catalog.json`: aufbereitete Produktkarten mit einzelnen Kaufbeträgen.
- `lineage.json`: ausschließlich lokale Rückverweise zu Archiv/Bonposition.
- `identity-candidates.json`: Wiederholungen für technische Namensprüfung.
- `migration.json`: stabile Katalogkennung und optionale Gruppenentscheidungen.

Gleiche Händlerbezeichnung/Sorte wird nach Entfernung von Größenangaben gruppiert;
Marken-/Sortentext und Fettstufen bleiben unterscheidbar. Preise sind kein Schlüssel.
Generische Namen bleiben separat. Keine Produktidentität oder EAN wird erfunden.
Mengeneinheiten werden nicht miteinander addiert. Fehlende Mengen bleiben offen.

Direkt zugeordnete Produktrabatte werden einmal berücksichtigt. Pfand, Rückgaben,
andere Waren und weitere Rabatte bleiben getrennt. Zahlungsanrechnungen/Gutscheine
sind kein zusätzlicher Warenrabatt. Kostenanteile werden kaufweise auf Cent gerundet.

## Verschlüsseltes Startpaket

`node modules/household-consumption/seal-catalog.mjs <catalog.json> <neuer lokaler
Ausgabeordner> <HTTPS-App-Basis-URL>` erzeugt ein Paket mit authentifizierter
AES-256-GCM-Verschlüsselung (zufällige 96-Bit-IV, 128-Bit-Tag und Katalogbindung).
Ein lokaler stabiler Schlüssel wird bei Updates mit jeweils neuer IV verwendet.
Authentifiziertes Entschlüsseln wird vor dem Schreiben geprüft.

Die Schlüsseldatei `access-key.bin`, der private Startlink und die `.webloc`-Datei
bleiben ausschließlich lokal unter `output/`. Sie dürfen nicht in Chat, Logs,
Git oder Deployment-Artefakte gelangen. Der Link transportiert den Schlüssel im
Fragment; der Browser entfernt ihn vor dem Netzwerkabruf und speichert ihn lokal.
GitHub erhält bei freigegebener Bereitstellung nur das verschlüsselte Paket.
Wer den vollständigen privaten Startlink erhält, kann den Katalog lesen.

`build-pages.mjs --sealed-catalog <HHC1-Datei>` bereitet ein lokales Artefakt mit
genau einer zusätzlichen verschlüsselten Datei vor. Der Standardbuild enthält
keine echten Daten. Der Builder veröffentlicht selbst nichts. Vor Bereitstellung
eines echten Pakets Datenumfang, Quellhashes, Schlüsselausschluss und Freigabe prüfen.

## Wiederaufnahme und Rückgabe

Demo und privater Katalog verwenden getrennte Speicherkennungen. Aktualisierungen
mit neuen Käufen erhalten bestehende Gruppenschlüssel und Bewertungen. Bei
Umbenennungen/Zusammenführungen ist eine explizite technische Migration erforderlich;
unbekannte bestehende Produktreferenzen dürfen nicht still gelöscht werden.

Private Bewertungen werden kompakt exportiert: Katalogkennung, Bewertungskennung,
Anzeigenamen, Zuordnungen, Anteile und noch offene Reihenfolge. Der Produktkatalog,
Originalbezüge und Rückgängig-Verlauf werden nicht mitgesendet. Dadurch bleibt die
Rückgabe großer Bewertungen per Messenger möglich. Lokaler Undo-Verlauf bleibt
beim normalen Fortsetzen erhalten; nach Wiederherstellung eines kompakten Exports
beginnt er leer. Zu große Nachrichten werden nicht gekürzt; Dateiexport bleibt möglich.

## Prüfgrenzen

Synthetische Tests prüfen Normalisierung, Sortentrennung, Rabatte, Archivhashes,
stabile IDs, Verschlüsselung/Manipulation, Schlüsseltransport ohne Serverübermittlung,
automatischen Start, isolierte Speicherung und kompakten Export-Rundlauf. Browser-QA
nutzt ausschließlich synthetische Katalogdaten. Kein automatischer Signal-Versand.

[AES-GCM-Parameter](https://developer.mozilla.org/en-US/docs/Web/API/AesGcmParams),
[URL-Fragment wird nicht an den Server gesendet](https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Fragment).

## Private Teilnehmerbeschriftungen

Optionale `people`-Metadaten stehen ausschließlich im verschlüsselten Katalog:
Rollen `a`, `b` und positive Versionsnummer. Namen werden in der ignorierten
Migrationseinstellung gepflegt, nie in öffentlichen Quellen/Tests. Beim ersten
Start einer neuen Metadatenversion werden nur Anzeigenamen und deren Version
aktualisiert. Bestehende Entscheidungen, Prozentwerte, Verlauf und Katalog-ID
bleiben erhalten. Spätere lokale Namensänderungen bleiben bis zur nächsten
expliziten Metadatenmigration bestehen. Die öffentliche Demo bleibt neutral.


## Verschlüsselte Produktbilder

Bildrecherche und Produktzuordnung liegen ausschließlich lokal unter `output/`.
`prepare-images.mjs <privater Katalogordner> <Rechercheordner>` prüft Rasterdaten,
verkleinert sie auf höchstens 384 × 384 Pixel und verschlüsselt jedes JPEG separat
mit AES-GCM (HHI1, eigene Zufalls-IV, authentifizierte Katalog- und Bildkennung).
`image-rejections.json` sperrt visuell verworfene Produkt/Bild-Paare. Quellen,
Kennzeichnung als Produkt- oder Beispielbild und gegebenenfalls Urheber/Lizenz
stehen nur im verschlüsselten Katalog. Ohne hinreichend passenden Treffer bleibt
bewusst der Platzhalter. Keine Zusammenlegung von Sorten durch Bildrecherche.

Die technische Migration liest `product-images.json`; bestehende IDs, Kaufbezüge,
Beträge und Bewertungen bleiben erhalten. Für `build-pages.mjs --sealed-catalog
<datei> --sealed-images <ordner>` enthält der Bildordner ausschließlich freigegebene,
vom Katalog referenzierte HHI1-Dateien. Originalbilder, Recherche und Schlüssel
werden nie kopiert. Die App entschlüsselt Bilder bei Bedarf und stellt sie über
kurzlebige Blob-URLs dar; beim Kartenwechsel wird die vorige URL freigegeben.
Es gibt keine Bildanfragen vom Telefon an Händler. Die Quellenverknüpfung öffnet
nur auf ausdrücklichen Klick mit `noreferrer`. Fehlende oder beschädigte Bilder
blockieren weder Bewertung noch Export. Die öffentliche Demo bleibt synthetisch.
