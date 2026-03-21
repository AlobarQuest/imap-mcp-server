"""Pydantic models for IMAP MCP server."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AccountConfig(BaseModel):
    """Configuration for a single IMAP/SMTP account."""

    name: str
    email: str
    imap_host: str
    imap_port: int = 993
    smtp_host: str
    smtp_port: int = 587
    username: str
    password: str


class AccountInfo(BaseModel):
    """Public account info returned by list_accounts."""

    name: str
    email: str
    status: str


class EmailSummary(BaseModel):
    """Summary of an email for list/search results."""

    id: str
    subject: str
    sender: str = Field(alias="from", serialization_alias="from")
    date: str
    is_read: bool
    has_attachments: bool
    preview: str


class Attachment(BaseModel):
    """Email attachment metadata."""

    filename: str
    size: int
    content_type: str


class EmailDetail(BaseModel):
    """Full email detail."""

    id: str
    subject: str
    sender: str = Field(alias="from", serialization_alias="from")
    to: list[str]
    cc: list[str]
    date: str
    body_text: str
    body_html: str
    attachments: list[Attachment]


class SendResult(BaseModel):
    """Result of sending an email."""

    success: bool
    message_id: str | None = None


class UpdateResult(BaseModel):
    """Result of mark_read / move / delete operations."""

    success: bool
    updated_count: int = 0
    moved_count: int = 0
    deleted_count: int = 0


class ErrorResponse(BaseModel):
    """Structured error response."""

    error: bool = True
    code: str
    message: str
    account: str | None = None
