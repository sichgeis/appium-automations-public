# Projektregeln

- Deutsch kommunizieren. Ausschließlich eigene Bons verarbeiten.
- Keine Käufe, Coupons, Kontoänderungen, Logouts oder Löschungen.
- Kein Reset/Neuinstallieren: noReset=true, fullReset=false. Keine automatischen Dialogzustimmungen.
- Echte UI-Dumps, Screenshots und Bons nur mit ausdrücklicher Modellfreigabe lesen oder übertragen.
- Zugangsdaten, Geräte-/Teamkennungen und persönliche Daten nicht in Git/Chat/Logs.
- config.local.json, data/, output/, .venv/, .appium/ und node_modules/ bleiben lokal.
- Keine Selektoren, Kennungen, APIs oder Exportfunktionen erfinden. Gerätestests und synthetische Tests unterscheiden.
- Appium nur 127.0.0.1, keine relaxed-security-Schalter. Exklusive Gerätesperre.
- Zeitraum vor Export klären, Originaltransport vor großen Läufen prüfen.
- Erfolg erst nach Format-/Bonzuordnung und erneutem Archivhashvergleich markieren.
- Nach Änderungen passende Tests einmal ausführen, erfolgreiche Tests nur bei neuen Gründen wiederholen.
- Python: `.venv/bin/python -m unittest discover -s tests -q`.
- Web: `npm --prefix modules/household-consumption test`.
- Pages enthält ausschließlich die synthetische Web-App aus der Positivliste des Builders.
- Private Daten dürfen auch über Git-Historie, Issues, Actions oder Release-Artefakte nicht veröffentlicht werden.
