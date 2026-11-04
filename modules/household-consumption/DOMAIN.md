# Fachmodell

## Begriffe und Beziehungen

- **Kaufposition:** Ein Lebensmittel auf einem konkreten Bon, mit Originalbezug,
  Betrag, Datum und belegter Menge. Unveränderliche Herkunft für die Auswertung.
- **Produktgruppe:** Wiederkehrendes konkretes Produkt, nicht nur eine Kategorie
  wie „Schokolade“. Enthält mehrere Kaufpositionen und hat eine stabile lokale ID.
- **Nutzungszuordnung:** Hauptsächlich A, hauptsächlich B oder gemeinsam. Gilt als
  Standard für alle Käufe der Gruppe, auch für später importierte Käufe.
- **Kostenanteil:** Von der Nutzung getrennte Rechenannahme, anfangs 100/0,
  0/100 bzw. 50/50; manuell änderbar. Kein gemessener Verbrauchsanteil.
- **Ausnahme:** Ein einzelner Kauf kann vom Gruppenstandard abweichen, etwa bei
  einer Feier. Die Ausnahme hat Vorrang und bleibt beim nächsten Import erhalten.
- **Prüffall:** Unklare Lebensmittelzugehörigkeit, Produktidentität, Menge oder
  Rabattverknüpfung. Keine automatische Zuordnung zur Gruppe „gemeinsam“.

## Identität und Deduplizierung

Bonpositionen über Händler + Originalhash + Positionsnummer identifizieren.
Diese Herkunft bleibt ausschließlich im lokalen Paket; kein Originalpfad,
Filialname, Zahlungsmerkmal oder Fiskalcode muss zur Web-App übertragen werden.

Aktuelle Gruppierung: gleiche Händlerbezeichnung und Sorte, Größenangaben ignorieren.
Markentext, Sorten und Fettstufen bleiben erhalten. Angebote werden nicht getrennt.
Preisspannen sind Orientierung; Kaufbeträge bilden die Grundlage der Kostenaufteilung.
Generische unklare Bezeichnungen bleiben separat. Keine unscharfe Zusammenführung.
Gruppen-IDs bleiben bei Namensänderungen stabil; keine laufend neu berechneten
Namenshashes als dauerhafte IDs verwenden.

## Zustände und wichtige Übergänge

Importiert → Lebensmittelstatus prüfen → offen → zugeordnet.
„Später“ bleibt offen; „kein Lebensmittel“ wird ausgeschlossen, bleibt korrigierbar.
Prüfhinweise können zusätzlich zu einer Zuordnung bestehen.

Ereignisse: Paket importiert, Gruppe bestätigt/zusammengeführt/aufgeteilt,
Zuordnung gesetzt, Anteil geändert, Kauf-Ausnahme gesetzt, Entscheidung
zurückgenommen. Änderungen mit vorherigem Wert lokal halten; Export enthält
Schema-Version, Paketidentität und Gruppenbezüge.

Bestätigter Ablauf: Eine Person bewertet zuerst vollständig, die zweite optional
unabhängig auf ihrem eigenen Gerät. Keine Synchronisierung oder automatische
Zusammenführung. Jede Bewertung hat eine eigene Kennung und optional einen Namen
der bewertenden Person, unabhängig von den beiden Verbrauchenden. Beide dürfen
ihre jeweilige Bewertung ändern. Import dient der expliziten Wiederherstellung.
Vor Übernahme anzeigen, ob es dieselbe oder eine andere Bewertung ist, und den
vorherigen Stand lokal sichern.
Eine geänderte Gruppenzuordnung gilt im MVP rückwirkend für den gewählten Datensatz;
zeitlich abweichende Käufe benötigen eine explizite Ausnahme.

## Mengen und Geld

- Geld ganzzahlig in Cent, Mengen als Dezimalwerte mit Einheit. Stück, kg und
  Liter getrennt ausweisen. Unterschiedliche Produkte nicht zu einer scheinbar
  sinnvollen Gesamtmenge addieren.
- Kaufhäufigkeit = Anzahl unterschiedlicher Bons mit Produkt; Positionsanzahl und
  bekannte Gesamtmenge zusätzlich anzeigen. Preisbereich nur für vergleichbare
  Einheiten; fehlende Einzelpreise nicht aus einem Positionsbetrag erfinden.
- Zugeordneter Betrag A = kaufbezogener Betrag × Kostenanteil A, kaufweise auf
  Cent runden; B erhält den Rest. Regel für negative Beträge ebenso festlegen,
  damit keine Centbeträge verschwinden.
- Direkt zuordenbare Produktrabatte reduzieren genau den zugehörigen Kauf einmal.
  Unzugeordnete Bon-/Partnerrabatte separat zeigen, zunächst nicht proportional
  verteilen. Ein Export darf deshalb einen offenen Rabattbetrag haben.
- Pfand separat, keine Lebensmittelkosten. Rückgaben mit belegtem Produktbezug
  mindern dessen Kosten; unklare Rückgaben bleiben separat. Nichtlebensmittel,
  Zahlungsanrechnungen und Gutscheine sind keine zusätzlichen Lebensmittelkosten.
- Keine künstlichen Differenzpositionen. Unbekannt bleibt unbekannt. Für Summen
  die enthaltenen, ausgeschlossenen und offenen Beträge nachvollziehbar ausweisen.

Die Auswertung nennt Warenkosten vor unzugeordneten Bonrabatten, zugeordnete
Produktrabatte, offene Rabatte und Kostenannahmen getrennt. Sie behauptet keine
vollständige Aufteilung der Kartenbelastungen. Eine Summenbrücke zum importierten
Datensatz zeigt Lebensmittel, andere Waren, Pfand, Rückgaben und Rabatte.

## Hypothesen und noch zu prüfende Annahmen

- Hypothese: Eine Person verursacht mehr Lebensmittelkosten; Ergebnis offen.
- Annahme: Eine typische Nutzung pro Produkt genügt meistens; Einzelkäufe reichen
  als Ausnahmen. Nach den ersten Produktkarten überprüfen.
- Entscheidung: Unabhängige Gerätestände mit Export/Dateiteilen; zweite Bewertung
  optional. Empfangene Dateien behalten ihre Bewertungsidentität.
- Entscheidung: Größen und Angebote gemeinsam; Sorten/Markenbezeichnungen unterscheidbar.
- Offen: Welche Kosten-/Mengenansicht beantwortet die Haushaltsfrage am besten?
- Entscheidung: Kein zentraler, geräteübergreifender Datenstand benötigt.
