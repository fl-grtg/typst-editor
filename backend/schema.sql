-- users/sessions replace accounts.json + sessions.jsonl. Rest: docs, shares, comments.

CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT '' -- base64 PNG (64px, scaled by frontend)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    expires TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS docs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New Document',
    content TEXT NOT NULL DEFAULT '',
    yjs BLOB, -- CRDT update bytes (identities!): never rebuild from text, else duplicated text
    folder TEXT NOT NULL DEFAULT '', -- folder in the sidebar ('' = top level)
    trashed INTEGER NOT NULL DEFAULT 0, -- trash: 1 = trashed, 2nd delete = permanent
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_owner ON docs(owner);
CREATE UNIQUE INDEX IF NOT EXISTS idx_docs_owner_title ON docs(owner, title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_docs_updated ON docs(updated_at);

CREATE TABLE IF NOT EXISTS shares (
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    username TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'reviewer',
    PRIMARY KEY (doc_id, username)
);
CREATE INDEX IF NOT EXISTS idx_shares_doc ON shares(doc_id);

-- parent_id NULL = top-level comment, else reply (mini chat). anchor = 1-based line number.
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    anchor INTEGER NOT NULL DEFAULT 1,
    quote TEXT NOT NULL DEFAULT '', -- marked span: moves along, gone = thread gone
    text TEXT NOT NULL DEFAULT '',
    parent_id TEXT NULL REFERENCES comments(id) ON DELETE CASCADE,
    resolved INTEGER NOT NULL DEFAULT 0, -- done flag (db.py migrates legacy rows)
    author TEXT NOT NULL DEFAULT '', -- display name override (MCP: API key name, else '')
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_doc ON comments(doc_id);

-- folders: created explicitly (even empty), kind 'doc' or 'tpl'. Docs/templates carry the name as attribute.
CREATE TABLE IF NOT EXISTS folders (
    owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'doc',
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner, kind, name)
);
CREATE TABLE IF NOT EXISTS invites (
    -- link invites: token -> doc + role.
    token TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'reviewer',
    created_at TEXT NOT NULL
);

-- history: snapshots per doc (restore + diff).
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    content TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_doc ON snapshots(doc_id, created_at);

-- templates: global per account, not per document.
CREATE TABLE IF NOT EXISTS templates (
    owner TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    name TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    line TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner, name)
);

-- api_keys: MCP/agent access. Only the sha256 hash is stored, the secret is
-- shown once at creation. role caps doc_role() (min), never owner/admin.
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    prefix TEXT NOT NULL DEFAULT '',
    key_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'editor',
    expires_at TEXT NOT NULL DEFAULT '',
    last_used TEXT NOT NULL DEFAULT '',
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(username);

-- FTS5 index over docs(title, content) for /api/search + MCP search.
-- External-content table keyed by docs.rowid (docs.id is TEXT, so FTS
-- content-sync is not an option); triggers keep it in sync. Fresh DBs get
-- it from here, existing DBs via db.py _migrate_v12 (same DDL + rebuild).
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(title, content, tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS docs_fts_ai AFTER INSERT ON docs BEGIN
  INSERT INTO docs_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS docs_fts_ad AFTER DELETE ON docs BEGIN
  DELETE FROM docs_fts WHERE rowid=old.rowid;
END;
CREATE TRIGGER IF NOT EXISTS docs_fts_au AFTER UPDATE ON docs
  WHEN old.title IS NOT new.title OR old.content IS NOT new.content BEGIN
  DELETE FROM docs_fts WHERE rowid=old.rowid;
  INSERT INTO docs_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
END;

-- files: one row per on-disk attachment (doc_id, relative path, size,
-- mtime, type). Quota and search read this table, never the filesystem.
-- FK CASCADE: hard doc delete drops the rows (docs.py owns that path).
CREATE TABLE IF NOT EXISTS files (
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    type TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (doc_id, path)
);
CREATE INDEX IF NOT EXISTS idx_files_doc ON files(doc_id);

-- notifications: minimal backend write path (services/notifications.py),
-- inbox UI follows in Wave 3D (owns routers/notifications.py). No FK to
-- docs on purpose: the inbox keeps its text snapshot after doc delete.
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    recipient TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT '',
    doc_id TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient, created_at);

-- read_tokens: token-hash -> doc for account-less reading
-- (routers/readmode.py, no UI in Wave 1). Revoke = DELETE the row.
CREATE TABLE IF NOT EXISTS read_tokens (
    token_hash TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    hint TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_read_tokens_doc ON read_tokens(doc_id);
