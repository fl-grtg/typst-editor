# Projekte und private Module

Es gibt nur Projekte. Migration 16 wandelt bestehende Dokumentordner automatisch um; Dokumente ohne Ordner erhalten ein eigenes Projekt. Dokument-IDs, lokale Dateien und bestehende Einzelfreigaben bleiben erhalten. Leere Ordner werden leere Projekte, ausschließlich gelöschte Dokumente bleiben archiviert. Private Bibliotheksordner bleiben nur interne Metadaten älterer Clients.

Ein Projekt kann mehrere unabhängig kompilierbare Typst-Dokumente enthalten. Alle Dokumente verwenden dieselbe Projektbibliothek mit Templates, Bib, CSV und weiteren Textressourcen. Dokumentlokale Dateien haben bei gleichem Pfad Vorrang. Ein Projekt verwendet keine lebenden Verknüpfungen auf private Module.

Der linke Projektbaum zeigt Dokumente, gemeinsame Ressourcen und lokale Dateien. Auch ein Projekt mit nur einem Dokument zeigt dieses als Untereintrag. Aktionen am Projekt sind Icons. Mitglieder werden ausschließlich über Teilen oben rechts verwaltet. Bei alten Einzelfreigaben bleibt der Zugriff auf das bisherige Dokument begrenzt; sie werden dort entsprechend gekennzeichnet.

## Module übernehmen

Mit mindestens Lesezugriff lassen sich Projektmodule in die eigene private Sammlung übernehmen. Private Module lassen sich in eigene oder gemeinsam bearbeitete Projekte übernehmen. Beim Einfügen eines privaten Moduls kopiert die Oberfläche zuerst das Modul ins Projekt und fügt anschließend den Verweis auf die Projektkopie ein.

Ein Pull kopiert den statisch erkennbaren Text-Abhängigkeitsbaum. Relative Pfade werden auf die Zielnamen angepasst. Namenskonflikte werden vor dem Schreiben durch Umbenennen oder Abbruch geklärt; bestehende Ressourcen werden nicht überschrieben. Auch Abhängigkeiten können einen eigenen Zielnamen erhalten. Quelle und Ziel bleiben anschließend unabhängig. Dynamische Dateipfade und Binärdateien müssen zusätzlich geprüft werden.

Dokumentgäste aus alten Einzelfreigaben dürfen nur die bereits für ihre Dokumente sichtbaren Module übernehmen. Projektmitglieder können die ganze Projektbibliothek lesen. Schreiben im Zielprojekt erfordert dort Editor- oder Ownerrechte. Ein veralteter Vorschautoken oder fehlende Quota bricht die gesamte Übernahme ohne Teiländerung ab.

## Rechte, Schnittstellen und Papierkorb

Owner verwalten Projektmitglieder und löschen Projekte; Editoren bearbeiten Projektinhalte und legen Dokumente an. Entfernen eines Mitglieds entfernt Restfreigaben auf Projektdokumenten und beendet offene Sitzungen. Einladungslinks dieser Dokumente werden wie bei bisherigen Freigaben ungültig, damit alte Links keinen erneuten Beitritt ermöglichen.

REST verwaltet Projekte unter `/api/projects`. Modul-Pulls verwenden `/api/library/pull-preview` und `/api/library/pull`. MCP ergänzt `/projects/{id}/docs/{Titel}/...` und `/projects/{id}/resources/...`; alte `/docs`- und `/shared`-Pfade bleiben kompatible Aliase. Dokumenttitel bleiben innerhalb eines Projekts eindeutig; verschiedene Projekte dürfen gleiche Titel enthalten. Mehrdeutige alte MCP-Titelpfade erfordern den eindeutigen Projektpfad. Dokumentgäste nutzen weiterhin `/shared`; `/projects` listet nur eigene Projekte und Mitgliedschaften. Neue Dokumente über REST, MCP und ZIP-Import werden unmittelbar einem Projekt zugeordnet.

Projektressourcen zählen zum Speicher des Besitzers. Persönliche Originale und Projektkopien sind getrennte Daten. Neue Schreiboperationen prüfen die Quota auf derselben SQLite-Verbindung innerhalb der Schreibtransaktion. Die automatische Migration bestehender Daten wird nicht durch eine inzwischen erreichte Quota blockiert.

Projektlöschung archiviert das Projekt und verschiebt Dokumente in den Papierkorb. Die Bibliothek bleibt für Restore erhalten. Wiederherstellen eines Dokuments aktiviert das Projekt; endgültige Löschung des letzten Dokuments entfernt ein archiviertes Projekt vollständig. Ein vollständiges Serverbackup sichert die Projektdaten und Mitgliedschaften in der Datenbank.

Kopieren und Verschieben erhalten vorhandene Unterordnerpfade. Verschieben zwischen verschiedenen Besitzern erfordert den Quellbesitzer; Editoren können stattdessen eine unabhängige Kopie anlegen. Projekt-ZIP steht auf allen Projekttabs auch für Leser bereit und enthält sämtliche für sie sichtbaren Dokumente, Module und Dateien.

Das Grundschema wird beim Start durch die versionierten Datenbankmigrationen ergänzt; auch frische Datenbanken durchlaufen diese Migrationen.
