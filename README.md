# Typst Editor

Kollaborativer Typst-Editor im Browser: links CodeMirror, rechts Live-PDF.
Ein Prozess (FastAPI + pycrdt), SQLite als DB, kein Node nötig.

## Start

```bat
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Danach `http://127.0.0.1:8000` öffnen, registrieren, losschreiben.
CodeMirror-Bundle neu bauen (nur nach `cm-build/entry.js`-Änderung):

```bat
cd cm-build && npm run build
```

## Was drin ist

- **Editor**: Typst-Highlighting, Autocomplete (nur Tab), Hover-Doku, Suchen/Ersetzen, Fehler als rote Zeile, Zoom/Schrift/Split/Sidebar persistent, Lesemodus, Mobile
- **Live-Sync**: Yjs über Python-Server, Live-Cursor, Presence, Autosave (Ctrl+S sofort)
- **Verlauf**: Auto-Snapshots beim Speichern + manuell, Diff-Ansicht, Wiederherstellen (Uhr-Icon)
- **Ordner + Suche + Papierkorb**: Sidebar gruppiert, Drag&Drop, Volltextsuche mit Treffer-Sprung, 2-stufiges Löschen, Duplizieren (⧉)
- **Kommentare**: Threads mit Quote-Anker, Antworten, @-Mentions, resolved-Haken, Badge-Sprung
- **Teilen**: per Username (owner/editor/reviewer) oder Link-Token mit Rolle
- **Dateien**: Upload + Drag&Drop, `#image`/`#include` per Klick, `.typ/.bib/.csv` als Tabs (Preview bleibt main)
- **Vorlagen**: global pro Account, Sidebar + Popup
- **Werkzeuge**: Symbol-Palette (Ω), Farb-Picker (`#text`-Rahmen), Klick-Sync beidseitig, Outline
- **Export**: `.typ`, PDF, PNG, SVG, alles als `.zip`-Backup (Einstellungen → Backup)
- **Offline**: PWA-Shell (Manifest + Service Worker), grüner/roter Netz-Punkt; Sync und Saves holen auf

## Hinweise

- Reviewer sehen alles live, schreiben aber nicht (ihre Sync-Updates verwirft der Server).
- Verlauf speichert max. 50 Stände pro Doc, Auto höchstens alle 15 Minuten.
- Git-Remote-Sync gibt es nicht – dafür ZIP-Backup und `.typ`-Download.
