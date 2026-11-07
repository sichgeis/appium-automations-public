# Haushaltsverbrauch

Mobiler Swipe-Prototyp mit ausschließlich synthetischen Produkten.
Die veröffentlichte Version ist über den separat geteilten HTTPS-UUID-Link erreichbar.

## Bedienung

Rechts: hauptsächlich Person A (anfangs 100/0), links: hauptsächlich Person B
(0/100), hoch: gemeinsam (50/50). Namen und Kostenanteile lokal änderbar.
Tasten sind eine Alternative zum Wischen. Kurze, diagonale und nach unten
gerichtete Gesten entscheiden nichts. Außerhalb der Karte lässt sich scrollen.

Wiederholungskäufe desselben konkreten Produkts gehören auf eine Karte. Sorte,
Marke und Packungsgröße bleiben unterscheidbar. Die Beispielkarten sind bereits
synthetisch zusammengefasst; ein echter Deduplizierer ist noch nicht implementiert.
Auswertung zeigt Kostenannahmen, keine gemessenen Verzehrmengen.

## Fortsetzen und Rückgabe

Jeder Browser speichert seine unabhängige Bewertung automatisch. Eine eigene
Kennung und optional ein Name unterscheiden Bewertungen. Keine Synchronisierung.
Dateidownload und natives Teilen-Menü ermöglichen die Rückgabe per Mail/Messenger.
Erst der Nutzer wählt Empfänger und versendet. Export ist kein Empfangsnachweis.

JSON-/Textdateien können mit Vorschau wiederhergestellt werden. Der vorherige
Stand wird in einem lokalen Rückholplatz gesichert. Dieser Platz hält genau den
Stand vor dem letzten Import; dauerhaft gewünschte Bewertungen als Dateien behalten.
Browserdaten können verloren gehen. Keine privaten Daten im Repository speichern.

## Lokal starten und prüfen

```sh
npm run dev
npm test
npm run build:pages
```

Kein Frontend-Bibliotheksdownload erforderlich; Node für Tests/Build und Python
für den lokalen Server. HTML/CSS/JavaScript, lokale Speicherung, keine externen
Bilder, Tracker, Schriften oder Datenübermittlung beim Swipen.

Zielbrowser: Safari/iOS und Chrome/Android. Responsive Browserprüfung ersetzt
keine echten Gerätetests. Native Share-API-Fälle werden mit Testdoubles geprüft.

Siehe [Fachregeln](DOMAIN.md), [Technik](IMPLEMENTATION.md) und [Pages](PUBLISHING.md).

## Signal auf iPhone

Dateiteilen verwendet bevorzugt eine Textdatei mit wiederherstellbarem JSON und
übergibt keine zusätzlichen Text-/Titelbestandteile neben dem Anhang. Falls
Signal dennoch keine Datei übernimmt, „Als Nachricht teilen“ verwenden. Das
übergibt den vollständigen kompakten Bewertungstext ohne Anhang. Empfänger können
ihn über „Text wiederherstellen“ einfügen und vor Übernahme prüfen. Nachrichten
über 32 KB werden nicht geteilt oder gekürzt; dafür den Dateiexport verwenden.
Native Signal-Kompatibilität ist noch nicht auf einem echten Gerät bestätigt.

## Technische Katalogmigration

Eigene geprüfte Daten können lokal technisch vorbereitet werden; kein sichtbarer
Produktimport ist erforderlich. Automatischer Start mit privatem Link und lokaler
Entschlüsselung ist implementiert. Der öffentliche Standardbuild enthält weiterhin
ausschließlich synthetische Daten. Verschlüsselte echte Pakete bedürfen gesonderter
Bereitstellung. Schlüssel bleiben lokal. Siehe [Migration](MIGRATION.md).

Packungsgrößen und Angebotspreise werden innerhalb gleicher Händlerbezeichnung
und Sorte zusammengefasst. Preisbereiche dienen als Orientierung; tatsächliche
Kaufbeträge bestimmen die Kostenanteile. Keine exakte Verzehrmessung.


Seit 07.11.2026: explizit geprüfte markenübergreifende Verbrauchsgruppen und aufgelöste Bonkürzel. Konsensbewertungen werden übernommen; Konflikte und Teilbewertungen bleiben offen. Sichere Migration und Erhalt der früheren Bewertung: [Migration](MIGRATION.md).
