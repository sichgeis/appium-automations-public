# Grenzen der Positionsauswertung

Originalintegrität und Artikelinterpretation sind unabhängig zu prüfen.
Eine erhaltene Originaldatei und eine passende Gesamtsumme beweisen keine richtige
Zuordnung von Produktnamen, Mengen, Rabatten oder Kategorien.

Bekannte Fehlerklassen älterer Parser: Zwischensummen können als Artikel erscheinen,
getrennte Namens-/Mengenzeilen können ihre Zuordnung verlieren und künstliche
Prüfdifferenzen können Summenfehler verdecken. Gewichtszeilen, Pfand, Rückgaben und
nicht zugeordnete Rabatte benötigen eigene Behandlung. Die synthetischen
Charakterisierungstests dokumentieren auch noch bestehende Einschränkungen.

Das lokale Modul `receiptbot.quality` untersucht eine vorhandene CSV lesend.
`receiptbot.semantic_review` validiert gespeicherte, originalhashgebundene
Prüfentscheidungen und exportiert sie separat. Es führt keine neue Modellprüfung
aus. Echte Bonverarbeitung durch Modelle benötigt gesonderte Zustimmung.
Keine personenbezogenen Auditbefunde sind in dieser öffentlichen Dokumentation enthalten.
