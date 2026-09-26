# Typst Editor – Roadmap

Stand: alle B-Punkte + Klick-Sync drin (Tag `base-working` = Stand davor).
Referenz-Version bei Problemen: s. `BASELINE.md`.

Vergleichsbasis: offizielle [Typst-Webapp-Doku](https://typst.app/docs/web-app/)
und deren [Roadmap](https://typst.app/docs/roadmap/) (Version History, Ordner,
Outline, Symbol-/Farb-Picker, Cursor in Preview, Change Tracking).

## A. Drin

- Editor: CodeMirror + Typst-Lezer, Autocomplete (`#`-Befehle, Dateien/Vorlagen,
  Labels, Doc-Wörter; nur Tab übernimmt), Hover-Doku, Suchen/Ersetzen
  (Ctrl+F, Treffer-Mark, Ersetzen/Alle, Aa), Fehler als rote Zeile + Hover
  (nur echte Errors), Zoom/Schrift/Split/Sidebar persistent, Lesemodus, Mobile
- Sync: Yjs + pycrdt-Server, Live-Cursor, Presence-Punkte, Autosave,
  Reviewer read-only
- Kommentare: Threads + Antworten, Quote-Anker wandert mit, Gutter-Marker,
  Karte an der Zeile
- Dateien: Manager mit Upload, `#image`/`#include` per Chip-Klick, Shadow-Files
- Vorlagen: global pro Account, Sidebar + Popup, Öffnen/Bearbeiten/Löschen
- Teilen: per Username, Rollen owner/editor/reviewer (Reviewer kommentiert,
  schreibt nicht — wie Typsts review-only)
- Konto: Register/Login, Tutorial-Doc, Avatar, Name/Passwort, Account-Löschen
- Export: `.typ` + PDF + PNG (Canvas) + SVG (Bundle, mit Fallback-Meldung)
- Tabs: `main.typ` + `.typ/.bib/.csv` aus dem Manager, Preview bleibt immer main
- Outline: `= `-Zeilen in der Sidebar, Klick springt in die Zeile
- Kommentare: `resolved`-Haken, Edit nur Autor, Badge-Zähler → Sprung zum nächsten
- Ansicht: 3er-Segment Editor/Split/Preview (statt 1 Lesemodus-Button)
- Starter: Leer, Bericht, Folien bei „Neu" (Inhalt kommt mit dem Create)
- Speichern: `Ctrl+S` sofort, Wortzähler in der `#save`-Anzeige
- Upload: Drag&Drop auf den Editor wie Manager
- Teilen: per Link (Token, `?join=…`) + Rolle direkt änderbar
- Doku: Dark Mode (`prefers-color-scheme`), Onboarding-Karte bei leerem Stand
- Klick-Sync beidseitig (⇄-Toggle): Editor→Preview proportional,
  Preview→Editor per Text-Anker exakt (Tabellen-Zellen → Quellzeile), sonst Anteil
- Fixes: kein Cursor-Klau bei Fehlern, PDF-Export mit Shadows, Login-strip,
  Rename zieht Kommentare mit, Datei-Tab frisst kein Main mehr (Healer/Sync/Save)
- Verlauf: Auto-Snapshot beim Speichern (max 50, alle 15 Min) + manuell,
  Diff-Ansicht, Wiederherstellen live an alle (Uhr-Icon)
- Ordner für Docs in der Sidebar (anlegen per Neu-Dialog, Drag&Drop,
  umbenennen/auflösen/einklappen persistent)
- Symbol-Palette: suchen + an Cursor einfügen (Ω-Icon)
- Farb-Picker: Auswahl mit `#text(fill: rgb("…"))` einrahmen
- Docs: Duplizieren (⧉, inkl. Dateien), Papierkorb (2-stufig),
  Suche über alle Docs mit Treffer-Sprung
- Kommentare: @-Mentions (Vorschlag + Farbe), Badge-Zähler im Header
- Fern: Backup als `.zip`, PWA-Basis (Manifest, Shell-Cache, Offline-Punkt)

## B. Erledigt in dieser Runde (war: je 1 Commit + Testlauf)

1–13 alle drin (s. A), plus Klick-Sync. Nichts offen.

C-Runde (danach, 1 Commit + 38 Smoke-Tests + 2 Reviews): Verlauf,
Ordner, Symbole, Farbe, Duplikat, Papierkorb, Suche, Mentions, Backup,
PWA-Basis + alle Review-Fixes (Save-Reihenfolge, Trash-Drop, Kommentar-Autoren,
Validierung, Gutter-Marker, Suche-Race, Dark-Lücken).

## C. Später (Ideen, teils von der offiziellen Typst-Roadmap)

- Fern: Change Tracking mit Annehmen/Ablehnen, Git-Remote-Sync, Offline-Vollbetrieb
  (Editieren + Sync-Warteschlange ohne Netz)
