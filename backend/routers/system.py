"""Health check and API fallback."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from backend import db

log = logging.getLogger("typst.main")

router = APIRouter()


@router.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def api_fallback(full_path: str) -> dict:
    raise HTTPException(404, "API gone")


@router.get("/healthz", response_model=None)
def healthz() -> dict | Response:
    try:
        con = db.connect()
        try:
            con.execute("SELECT 1").fetchone()
        finally:
            con.close()
    except Exception as e:
        log.warning("healthz db failed: %s", e)
        return JSONResponse(status_code=500, content={"ok": False})
    return {"ok": True}
