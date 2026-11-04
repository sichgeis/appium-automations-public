# Technik und Grenzen

`web/` enthält eine statische HTML/CSS/JavaScript-App ohne externe Abhängigkeiten.
`products.mjs` enthält ausschließlich erfundene Produkte, Preise und Kaufzahlen.
`core.mjs` enthält Zuordnung, Verlauf, Fortschritt und Gestenschwellen.
`backup.mjs` enthält versionierte Export-/Importformate und Dateiteilen.

Local Storage hält den unabhängigen Gerätestand. Entscheidungen werden erst nach
erfolgreichem Schreiben übernommen. Speicherfehler oder Änderungen in anderen
Tabs sperren ein stilles Überschreiben. Sicherungsimport prüft Format, Produktbezüge
und Anteile, zeigt eine Vorschau und sichert den bisherigen Stand vor Übernahme.
Keine serverseitige Speicherung oder Synchronisierung.

Der Export enthält Bewertungskennung, optionalen Bewertendennamen, Anzeigenamen,
Produktbezüge, Zuordnungen, Kostenanteile, Warteschlange und Undo-Verlauf. Diese
Daten verlassen das Gerät erst beim ausdrücklich ausgelösten Export/Teilen.
Dateinamen enthalten keine persönlichen Namen. JSON-Dateien werden über Web Share
angeboten; bei fehlender Unterstützung als inhaltsgleiche Textdatei oder Download.
Die App bestätigt keinen Versand oder Empfang.

Der Prototyp rechnet Kosten je Produktgruppe. Echter Bonimport, kaufweise Rechnung,
Pfand-/Rabattverarbeitung und automatische Deduplizierung sind noch geplant.
Die echte Auswertung soll den hashgeprüften strukturierten Daten lokal folgen;
Originale, Quellpfade und private Metadaten gehören nicht in das öffentliche Paket.
IndexedDB kann für größere echte Datensätze ergänzt werden.

Tests: `npm test`. Browserprüfung bei schmalen Viewports sowie Export-/Import-Rundlauf
sind erfolgt. Native iOS-/Android-Geräte und echte Share-Ziele sind separat zu prüfen.
