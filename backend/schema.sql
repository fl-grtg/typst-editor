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

-- parent_id NULL = top-level comment, else reply (mini chat). anchor = line number.
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    anchor INTEGER NOT NULL DEFAULT 0,
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
