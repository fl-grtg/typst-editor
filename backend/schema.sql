-- users/sessions statt accounts.json + sessions.jsonl. Rest: docs, shares, comments.

CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT '' -- base64-PNG (64px, Frontend skaliert)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    expires TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS docs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Neues Dokument',
    content TEXT NOT NULL DEFAULT '',
    yjs BLOB, -- CRDT-Update-Bytes (Identitaeten!): nie aus Text neu aufbauen, sonst Doppeltext
    folder TEXT NOT NULL DEFAULT '', -- Ordner in der Sidebar ('' = oben)
    trashed INTEGER NOT NULL DEFAULT 0, -- Papierkorb: 1 = gelöscht, 2. Löschen = endgültig
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_owner ON docs(owner);
CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_owner_title ON docs(owner, title COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS shares (
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    username TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'reviewer',
    PRIMARY KEY (doc_id, username)
);

-- parent_id NULL = Top-Kommentar, sonst Antwort (Mini-Chat). anchor = Zeilennummer.
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    anchor INTEGER NOT NULL DEFAULT 0,
    quote TEXT NOT NULL DEFAULT '', -- markierte Stelle: wandert mit, weg = Thread weg
    text TEXT NOT NULL DEFAULT '',
    parent_id TEXT NULL REFERENCES comments(id) ON DELETE CASCADE,
    resolved INTEGER NOT NULL DEFAULT 0, -- B3: Erledigt-Haken (db.py migriert Altbestände)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_doc ON comments(doc_id);

-- Ordner: explizit angelegt (auch leer), kind 'doc' oder 'tpl'. Docs/Templates tragen den Namen als Attribut.
CREATE TABLE IF NOT EXISTS folders (
    owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'doc',
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner, kind, name)
);
CREATE TABLE IF NOT EXISTS invites (
    -- Link-Einladungen: Token -> Doc + Rolle.
    token TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'reviewer',
    created_at TEXT NOT NULL
);

-- Verlauf: Snapshots pro Doc (Wiederherstellen + Diff).
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    content TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_doc ON snapshots(doc_id, created_at);

-- Vorlagen: global pro Account, nicht pro Dokument.
CREATE TABLE IF NOT EXISTS templates (
    owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    name TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    line TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner, name)
);
