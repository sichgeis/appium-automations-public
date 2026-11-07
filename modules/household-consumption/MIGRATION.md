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
Diese Basisidentität bleibt nachvollziehbar. Explizit geprüfte Verbrauchsgruppen dürfen danach Marken, Bio-Kennzeichnung und Händler übergreifen; bekannte unterschiedliche Geschmacksrichtungen und Fettstufen bleiben getrennt. Preise sind kein Schlüssel.
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


## Markenübergreifende Verbrauchsgruppen (07.11.2026)

`consumption_groups` in der lokalen Migration enthält stabile `key`, Anzeigename,
`detail`, alte Karten-IDs als `members` und die Entscheidungsevidenz. Nur explizite
Mitglieder werden zusammengefasst; keine unscharfe Namensähnlichkeit und keine
Gruppierung durch Bilder. `renames` löst geprüfte Bonkürzel ohne ID-Wechsel auf.
Bekannte Geschmacksrichtungen bleiben getrennt. Unklare Sorten werden weder
erraten noch anhand eines ähnlich aussehenden Produktbildes festgelegt.

Kaufpositions-IDs, Centbeträge und Originalbezüge bleiben erhalten. Der neue
Gruppenschlüssel ist von Name, Preis und späterem Bild unabhängig. Händlerliste,
Bonanzahl und Preisbereich werden aus allen Mitgliedern neu gebildet. Ein Bild
für eine markenübergreifende Gruppe ist als Beispielbild gekennzeichnet.

Der verschlüsselte Katalog enthält `regrouping` Version 1 mit vollständiger
Quell-/Zielzuordnung der bisherigen Karten. Die App migriert auf jedem Gerät
separat und speichert vorher den vollständigen Altstand in Local Storage unter
`household-before-grouping:<catalog-id>:<version>`. Ein Export dieses früheren
Stands ist im Sicherungsbereich möglich. Bei Schreibfehlern bleibt die aktive
Bewertung unverändert; kein automatisches Zurücksetzen.

Nur wenn alle bisherigen Mitgliedskarten dieselbe Kategorie **und denselben
Prozentwert** besitzen, wird die Gruppenentscheidung übernommen. Teilbewertete
Gruppen bleiben offen; widersprüchliche Entscheidungen werden ausdrücklich
als Konflikt vorgelegt. Keine Mehrheit oder Mittelung. Unveränderte Undo-Einträge,
Bewertungsidentität und lokale Namen bleiben erhalten; Undo für ersetzte Karten
wird nicht auf neue Gruppen umgedeutet. Die Gruppierung ist idempotent; unbekannte
IDs oder neuere Versionen werden abgewiesen. Alte kompakte Exporte bleiben mit
dieser Zuordnung importierbar, neue enthalten Gruppierungsmetadaten. Historische
separate Bewertungen/Analysen werden nicht überschrieben.

Bewusste Recovery-Kopien außerhalb des Browsers liegen nach Hostvorgabe unter
`~/backups/appium-automations/`, nicht neben aktiven Projektdateien. Der
Bildvorbereiter erzeugt keine zusätzlichen automatischen Registry-Snapshots.
