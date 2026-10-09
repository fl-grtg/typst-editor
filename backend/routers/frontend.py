"""Static frontend delivery."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend import deps

router = APIRouter()


FRONT_FILES = deps.IMMUTABLE_SHELL  # one asset set: served files = immutable-cache files


@router.get("/")
def frontend_root() -> FileResponse:
    try:
        return FileResponse(str(deps.ROOT / "index.html"))
    except (FileNotFoundError, RuntimeError, OSError):
        raise HTTPException(404, "Not found") from None


@router.get("/{name}")
def frontend_file(name: str) -> FileResponse:
    if name in FRONT_FILES:
        p = deps.ROOT / name
        if p.is_file():
            try:
                return FileResponse(str(p))
            except (FileNotFoundError, RuntimeError, OSError):
                pass
    raise HTTPException(404, "Not found")
