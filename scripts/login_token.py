#!/usr/bin/env python3
"""Internal maintenance for persistent #token= login links.

The links are not exposed in the web UI. Run this with the same DATA_DIR as
the app; the token is printed once and only its hash is stored. The token
lives in the URL fragment, which browsers never send to the server, so it
does not end up in access logs. The legacy ?token= query form still works.

Revoking stops future exchanges only. A session that was already created
from the link is a normal session and stays valid until it expires or is
revoked in the app.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import auth, db  # noqa: E402


def _user_exists(name: str) -> bool:
    con = db.connect()
    try:
        return con.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone() is not None
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Create, list or revoke internal #token= login links.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    create = sub.add_parser("create", help="Create a link and print its token once.")
    create.add_argument("username")
    create.add_argument("--base-url", default="", help="Also print a ready URL, e.g. http://127.0.0.1:8978")

    lst = sub.add_parser("list", help="List a user's links (ids and timestamps, never secrets).")
    lst.add_argument("username")

    revoke = sub.add_parser("revoke", help="Delete a link by id. Sessions already created from it stay valid.")
    revoke.add_argument("id")
    revoke.add_argument("--user", default="", help="Only revoke when the link belongs to this user.")

    a = ap.parse_args()
    db.init_db()

    if a.cmd == "create":
        if not _user_exists(a.username):
            raise SystemExit("unknown user: %s" % a.username)
        tid, token = auth.mint_login_token(a.username)
        print("id: %s" % tid)
        print("token: %s" % token)
        if a.base_url:
            print("url: %s/#token=%s" % (a.base_url.rstrip("/"), token))
        return

    if a.cmd == "list":
        for row in auth.list_login_tokens(a.username):
            print("%s\t%s\t%s" % (row["id"], row["created_at"], row["last_used"] or "-"))
        return

    if not auth.revoke_login_token(a.id, a.user):
        raise SystemExit("login token not found")
    print("revoked: %s" % a.id)


if __name__ == "__main__":
    main()
