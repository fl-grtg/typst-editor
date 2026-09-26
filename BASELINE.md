# Baseline

## Gute funktionierende Version

Commit `9768c75` — „Publish-Runde: Register, Rename, Settings/Konto, Templates,
Fehler-UX, Mobile, Tutorial".

Das ist die Referenz: alles unten Genannte läuft. Bei Problemen mit späteren
Änderungen hierher zurück (`git checkout 9768c75`).

Drin: Register/Login, Titel-Umbenennung, Tutorial-Doc pro Account, rote
Fehler-Karte mit Zeilensprung, Settings (Schrift/Zoom in `localStorage`,
Name/Passwort/Avatar/Account-Löschen), Mobile-Layout, Autocomplete + Hover,
Templates (Tabelle, Sidebar, Einfügen, Hochladen, Löschen), Kommentar-Threads
mit Antworten, Teilen per Username (Owner/Editor/Reviewer), Live-Sync via
Python (pycrdt), Medien-Manager, PDF/.typ-Download, Lesemodus.

## Simplifizierung (kein neues Verhalten)

Commit `ee7d146` — „Simple-code: Konstanten-Block, stepEd/stepPv, clampSplit,
leaveDoc, Ankerpfad vereint, Heartbeat raus".

Reines Aufräumen von `index.html` (57+/75−), verhaltensneutral bis auf drei
Vereinheitlichungen: Lese-Zoom-Min 50 → 30 (wie Haupt-Zoom), Split-Grenzen fix
15/85 % statt Toolbar-Messung, kein eigener 10s-Presence-Push mehr (macht
Awareness selbst).
