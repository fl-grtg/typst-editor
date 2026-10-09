"""Pydantic request bodies for the REST API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Login(BaseModel):
    username: str = Field(max_length=20)
    password: str = Field(max_length=200)


class Register(BaseModel):
    username: str = Field(max_length=20)
    password: str = Field(max_length=200)
    invite: str = Field(default="", max_length=200)


class DocCreate(BaseModel):
    title: str = Field(default="New document", max_length=100)
    content: str = Field(default="", max_length=200001)
    folder: str = Field(default="", max_length=40)


class DocSave(BaseModel):
    content: str = Field(max_length=200001)
    force: bool = False


class TitleSet(BaseModel):
    title: str = Field(max_length=100)


class TplSave(BaseModel):
    name: str = Field(max_length=100)
    content: str = Field(default="", max_length=200001)
    folder: str = Field(default="", max_length=40)


class Share(BaseModel):
    username: str = Field(max_length=20)
    role: str = Field(default="reviewer", max_length=20)


class CommentNew(BaseModel):
    anchor: int = Field(default=0, ge=0, le=10000000)
    text: str = Field(max_length=2001)
    parent_id: str | None = Field(default=None, max_length=100)
    quote: str = Field(default="", max_length=2000)


class AnchorSet(BaseModel):
    anchor: int = Field(ge=0, le=10000000)


class CommentEdit(BaseModel):
    text: str = Field(max_length=2001)


class ResolveSet(BaseModel):
    resolved: bool = True


class FolderSet(BaseModel):
    folder: str = Field(default="", max_length=40)


class FolderRename(BaseModel):
    old: str = Field(max_length=40)
    new: str = Field(max_length=40)


class SnapNew(BaseModel):
    label: str = Field(default="", max_length=80)


class SnapRestore(BaseModel):
    force: bool = False


class FileText(BaseModel):
    content: str = Field(default="", max_length=200001)


class InviteNew(BaseModel):
    role: str = Field(default="reviewer", max_length=20)  # editor | reviewer


class JoinBody(BaseModel):
    token: str = Field(max_length=200)  # POST body preferred: token never in URL/access log


class PwChange(BaseModel):
    old: str = Field(max_length=200)
    new: str = Field(max_length=200)


class NameChange(BaseModel):
    name: str = Field(max_length=20)
    password: str = Field(max_length=200)


class PwOnly(BaseModel):
    password: str = Field(max_length=200)


class AvatarSet(BaseModel):
    img: str = Field(default="", max_length=300000)


class KeyCreate(BaseModel):
    name: str = Field(default="", max_length=40, min_length=1)
    role: str = Field(default="editor", max_length=20)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
