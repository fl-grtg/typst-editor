import sqlite3

from backend import db


def test_proposal_author_migration_preserves_existing_accounts_and_is_idempotent():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    try:
        db._migrate_v23(con)
        con.execute("INSERT INTO suggestion_packages(id,project_id,author,title,files,created_at,updated_at) VALUES ('sp_old','p_old','alice','Old proposal','[]','now','now')")
        db._migrate_v26(con)
        db._migrate_v26(con)
        assert tuple(con.execute('SELECT author,author_name FROM suggestion_packages').fetchone()) == ('alice', '')
    finally:
        con.close()
