"""Project proposal packages."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from backend import db, deps, sync
from backend.constants import MAX_REQUEST_BYTES
from backend.services import change_packages as packages
from backend.services import projects, quota

log = logging.getLogger("typst.main")

router = APIRouter()


class Change(BaseModel):
    id: str = ""
    old_string: str = Field(max_length=200000)
    new_string: str = Field(max_length=200000)


class ProposalFile(BaseModel):
    id: str = ""
    kind: Literal["document", "resource", "file"]
    doc_id: str = Field(default="", max_length=100)
    path: str = Field(min_length=1, max_length=240)
    action: Literal["modify", "add", "delete", "rename"]
    target: str = Field(default="", max_length=240)
    base: str | None = Field(default=None, max_length=14000000)
    content: str | None = Field(default=None, max_length=14000000)
    binary: bool = False
    changes: list[Change] = Field(default_factory=list, max_length=500)


class PackageSave(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    files: list[ProposalFile] = Field(max_length=100)
    revision: int = 0


class Selection(BaseModel):
    revision: int
    file_id: str = ""
    change_id: str = ""


@router.get("/api/projects/{project_id}/proposals")
def list_packages(project_id: str, user: str = Depends(deps.me)) -> dict:
    with db.tx() as con:
        projects.require(con, project_id, user)
        rows = con.execute(
            """SELECT id,title,author,revision,accepted,created_at,updated_at,
               json_array_length(files) AS file_count,
               (SELECT COALESCE(SUM(MAX(COALESCE(json_array_length(value,'$.changes'),0),1)),0)
                FROM json_each(files)) AS change_count
               FROM suggestion_packages WHERE project_id=? AND json_array_length(files)>0 ORDER BY updated_at DESC""",
            (project_id,),
        ).fetchall()
        return {"packages": [dict(row) for row in rows]}


@router.get("/api/projects/{project_id}/proposals/{package_id}")
def read_package(project_id: str, package_id: str, user: str = Depends(deps.me)) -> dict:
    with db.tx() as con:
        projects.require(con, project_id, user)
        return packages.get(con, project_id, package_id)


async def _package_body(req: Request) -> PackageSave:
    # Manual parse here: the size-capped reader must see the body before any
    # framework buffering, and Invalid-body keeps the clean 400 shape.
    raw = await deps.read_capped_body(req, MAX_REQUEST_BYTES)
    try:
        return PackageSave.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(400, "Invalid request") from None


@router.post("/api/projects/{project_id}/proposals")
async def create_package(project_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "comments")
    body = await _package_body(req)
    if not body.files:
        raise HTTPException(400, "An empty package cannot be submitted")
    return await asyncio.to_thread(
        packages.save, user, project_id, body.title,
        [f.model_dump(exclude_defaults=True) for f in body.files])


@router.patch("/api/projects/{project_id}/proposals/{package_id}")
async def correct_package(
    project_id: str, package_id: str, req: Request, user: str = Depends(deps.me)
) -> dict:
    deps.limited(req, "comments")
    body = await _package_body(req)
    return await asyncio.to_thread(
        packages.save,
        user,
        project_id,
        body.title,
        [f.model_dump(exclude_defaults=True) for f in body.files],
        package_id,
        body.revision,
    )


@router.post("/api/projects/{project_id}/proposals/{package_id}/accept")
async def accept_package(
    project_id: str, package_id: str, body: Selection, req: Request, user: str = Depends(deps.me)
) -> dict:
    deps.limited(req, "comments")
    if body.change_id and not body.file_id:
        raise HTTPException(400, "Select the file containing the change")
    result, updates = await asyncio.to_thread(
        packages.accept, user, project_id, package_id, body.revision, body.file_id, body.change_id
    )
    try:
        for room, update, _ in updates:
            await sync.bcast(
                room["conns"],
                None,
                sync.blob(
                    sync.write_var(sync.MSG_SYNC), sync.write_var(sync.UPDATE), sync.write_var(len(update)), update
                ),
            )
    except Exception as e:
        # The mutation already committed: a broken broadcast must not surface
        # as a 500 (clients would retry and hit 409 "no longer pending").
        log.warning("proposal accept bcast: %s", e)
    return result


@router.delete("/api/projects/{project_id}/proposals/{package_id}")
def delete_package(project_id: str, package_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "delete")
    with db.tx() as con:
        role = projects.require(con, project_id, user)
        proposal = packages.get(con, project_id, package_id)
        if proposal["author"] != user and role != "owner":
            raise HTTPException(403, "Only the author or owner may delete the package")
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()[0]
        con.execute("DELETE FROM suggestion_packages WHERE id=?", (package_id,))
    quota.invalidate_quota_cache(owner)
    projects.notify(project_id)
    return {"ok": True}
