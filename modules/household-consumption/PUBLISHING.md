# GitHub Pages

Pages wird aus dem separaten `gh-pages`-Branch bereitgestellt. Der Web-Inhalt liegt
unter dem festen UUID-Pfad aus `pages.config.json`. Bei Updates den Pfad beibehalten.
Die UUID ist kein Zugriffsschutz. Nur synthetische Daten veröffentlichen.

`npm run build:pages` erstellt einen neuen lokalen Ordner unter
`output/household-consumption/` und nennt dessen Pfad. Eine feste Positivliste
kopiert sechs Web-Dateien und erzeugt neutrale Start-/Fehlerseiten, `.nojekyll`
und `robots.txt`. Keine Repositorywurzel oder privaten Daten zum Hosting kopieren.

Alle HTML-Seiten enthalten `noindex, nofollow`. Keine Sitemap oder Verlinkung von
der Startseite zur UUID. `robots.txt` sperrt Crawling nicht, damit unterstützende
Suchmaschinen `noindex` lesen können. Bei Projekt-Pages ist nur eine robots.txt
an der Domainwurzel maßgeblich, nicht die Datei im Repository-Unterpfad.

Diese Hinweise garantieren weder Geheimhaltung noch das Verhalten aller Suchmaschinen.
[Google zu noindex](https://developers.google.com/search/docs/crawling-indexing/block-indexing)
