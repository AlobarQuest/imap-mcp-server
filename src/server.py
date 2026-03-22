"""FastMCP server with IMAP/SMTP tools and health endpoint."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from .accounts import AccountRegistry
from .client import IMAPClient, SMTPClient
from .errors import IMAPError
from .models import ErrorResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize registry and clients
registry = AccountRegistry()
registry.load_from_env()

imap_clients: dict[str, IMAPClient] = {}
smtp_clients: dict[str, SMTPClient] = {}

for config in registry.list_all():
    imap_clients[config.name] = IMAPClient(config)
    smtp_clients[config.name] = SMTPClient(config)

# Create FastMCP app
mcp = FastMCP(
    "IMAP MCP Server",
    instructions="Multi-account IMAP/SMTP email server for Claude",
)


def _error(code: str, message: str, account: str | None = None) -> dict:
    return ErrorResponse(code=code, message=message, account=account).model_dump()


def _get_imap_client(account: str) -> IMAPClient | dict:
    """Get IMAP client or return error dict."""
    if account not in imap_clients:
        available = ", ".join(registry.names()) or "none"
        return _error(
            "ACCOUNT_NOT_FOUND",
            f"Account '{account}' not found. Available: {available}",
            account,
        )
    return imap_clients[account]


def _get_smtp_client(account: str) -> SMTPClient | dict:
    """Get SMTP client or return error dict."""
    if account not in smtp_clients:
        available = ", ".join(registry.names()) or "none"
        return _error(
            "ACCOUNT_NOT_FOUND",
            f"Account '{account}' not found. Available: {available}",
            account,
        )
    return smtp_clients[account]


# --- Tools ---


@mcp.tool()
async def imap_list_accounts() -> list[dict] | dict:
    """List all configured and available IMAP accounts."""
    results = []
    for config in registry.list_all():
        client = imap_clients.get(config.name)
        status = "disconnected"
        if client:
            try:
                healthy = await client.check_health()
                status = "connected" if healthy else "disconnected"
            except Exception:
                status = "error"
        results.append({"name": config.name, "email": config.email, "status": status})
    return results


@mcp.tool()
async def imap_list_emails(
    account: str,
    folder: str = "INBOX",
    limit: int = 20,
    offset: int = 0,
    unread_only: bool = False,
    since_date: str | None = None,
    search: str | None = None,
) -> list[dict] | dict:
    """List emails from a folder with optional filters.

    Args:
        account: Account name (e.g. 'adjustright')
        folder: Mailbox folder (default: INBOX)
        limit: Max emails to return (default: 20, max: 100)
        offset: Pagination offset (default: 0)
        unread_only: Only return unread emails
        since_date: ISO date string to filter emails since
        search: Text search in subject/sender
    """
    client = _get_imap_client(account)
    if isinstance(client, dict):
        return client

    limit = min(limit, 100)
    try:
        emails = await client.list_emails(
            folder=folder,
            limit=limit,
            offset=offset,
            unread_only=unread_only,
            since_date=since_date,
            search=search,
        )
        return [e.model_dump(by_alias=True) for e in emails]
    except IMAPError as exc:
        return _error(exc.code, str(exc), account)
    except Exception as exc:
        return _error("CONNECTION_TIMEOUT", str(exc), account)


@mcp.tool()
async def imap_read_email(
    account: str,
    email_id: str,
    folder: str = "INBOX",
) -> dict:
    """Read the full content of a single email.

    Args:
        account: Account name
        email_id: Email UID from list results
        folder: Mailbox folder (default: INBOX)
    """
    client = _get_imap_client(account)
    if isinstance(client, dict):
        return client

    try:
        detail = await client.read_email(uid=email_id, folder=folder)
        if detail is None:
            return _error("EMAIL_NOT_FOUND", f"Email {email_id} not found in {folder}", account)
        return detail.model_dump(by_alias=True)
    except IMAPError as exc:
        return _error(exc.code, str(exc), account)
    except Exception as exc:
        return _error("CONNECTION_TIMEOUT", str(exc), account)


@mcp.tool()
async def imap_search_emails(
    account: str,
    query: str,
    folder: str = "INBOX",
    limit: int = 20,
) -> list[dict] | dict:
    """Search emails across folders.

    Args:
        account: Account name
        query: Search string
        folder: Folder to search (use 'ALL' for all folders)
        limit: Max results (default: 20)
    """
    client = _get_imap_client(account)
    if isinstance(client, dict):
        return client

    try:
        results = await client.search_emails(query=query, folder=folder, limit=limit)
        return [e.model_dump(by_alias=True) for e in results]
    except IMAPError as exc:
        return _error(exc.code, str(exc), account)
    except Exception as exc:
        return _error("CONNECTION_TIMEOUT", str(exc), account)


@mcp.tool()
async def imap_send_email(
    account: str,
    to: list[str],
    subject: str,
    body: str,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict:
    """Send an email via SMTP.

    Args:
        account: Account name to send from
        to: List of recipient email addresses
        subject: Email subject
        body: Plain text body
        body_html: Optional HTML body
        cc: Optional CC recipients
        bcc: Optional BCC recipients
    """
    smtp = _get_smtp_client(account)
    if isinstance(smtp, dict):
        return smtp

    try:
        result = await smtp.send_email(
            to=to,
            subject=subject,
            body=body,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
        )
        return result.model_dump()
    except IMAPError as exc:
        return _error(exc.code, str(exc), account)
    except Exception as exc:
        return _error("SEND_FAILED", str(exc), account)


@mcp.tool()
async def imap_mark_read(
    account: str,
    email_ids: list[str],
    folder: str = "INBOX",
    read: bool = True,
) -> dict:
    """Mark emails as read or unread.

    Args:
        account: Account name
        email_ids: List of email UIDs
        folder: Mailbox folder (default: INBOX)
        read: True to mark read, False for unread (default: True)
    """
    client = _get_imap_client(account)
    if isinstance(client, dict):
        return client

    try:
        result = await client.mark_read(uids=email_ids, folder=folder, read=read)
        return result.model_dump()
    except IMAPError as exc:
        return _error(exc.code, str(exc), account)
    except Exception as exc:
        return _error("CONNECTION_TIMEOUT", str(exc), account)


@mcp.tool()
async def imap_move_email(
    account: str,
    email_ids: list[str],
    from_folder: str,
    to_folder: str,
) -> dict:
    """Move emails between folders.

    Args:
        account: Account name
        email_ids: List of email UIDs
        from_folder: Source folder
        to_folder: Destination folder
    """
    client = _get_imap_client(account)
    if isinstance(client, dict):
        return client

    try:
        result = await client.move_email(
            uids=email_ids, from_folder=from_folder, to_folder=to_folder
        )
        return result.model_dump()
    except IMAPError as exc:
        return _error(exc.code, str(exc), account)
    except Exception as exc:
        return _error("CONNECTION_TIMEOUT", str(exc), account)


@mcp.tool()
async def imap_list_folders(account: str) -> list[str] | dict:
    """List all mailbox folders for an account.

    Args:
        account: Account name
    """
    client = _get_imap_client(account)
    if isinstance(client, dict):
        return client

    try:
        return await client.list_folders()
    except IMAPError as exc:
        return _error(exc.code, str(exc), account)
    except Exception as exc:
        return _error("CONNECTION_TIMEOUT", str(exc), account)


@mcp.tool()
async def imap_delete_email(
    account: str,
    email_ids: list[str],
    folder: str = "INBOX",
    permanent: bool = False,
) -> dict:
    """Delete emails (move to Trash by default).

    Args:
        account: Account name
        email_ids: List of email UIDs
        folder: Source folder (default: INBOX)
        permanent: If True, permanently delete instead of moving to Trash
    """
    client = _get_imap_client(account)
    if isinstance(client, dict):
        return client

    try:
        result = await client.delete_email(uids=email_ids, folder=folder, permanent=permanent)
        return result.model_dump()
    except IMAPError as exc:
        return _error(exc.code, str(exc), account)
    except Exception as exc:
        return _error("CONNECTION_TIMEOUT", str(exc), account)


# --- Health Endpoint ---


async def _probe_accounts() -> dict[str, str]:
    """Probe all accounts with check_health() and return status dict."""
    statuses = {}
    for name, client in imap_clients.items():
        try:
            healthy = await client.check_health()
            statuses[name] = "connected" if healthy else "disconnected"
        except Exception:
            statuses[name] = "error"
    return statuses


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Combined health check — returns per-account status and overall readiness."""
    accounts_status = await _probe_accounts()

    any_connected = any(s == "connected" for s in accounts_status.values())
    if not accounts_status:
        overall = "no_accounts"
    elif any_connected:
        overall = "ok"
    else:
        overall = "degraded"

    return JSONResponse({"status": overall, "accounts": accounts_status})


@mcp.custom_route("/health/live", methods=["GET"])
async def liveness(request: Request) -> JSONResponse:
    """Liveness probe — process is up."""
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/health/ready", methods=["GET"])
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe — at least one account can authenticate."""
    accounts_status = await _probe_accounts()

    any_usable = any(s == "connected" for s in accounts_status.values())
    if not accounts_status:
        status_code = 503
        overall = "no_accounts"
    elif any_usable:
        status_code = 200
        overall = "ready"
    else:
        status_code = 503
        overall = "not_ready"

    return JSONResponse(
        {"status": overall, "accounts": accounts_status},
        status_code=status_code,
    )


def create_app():
    """Create and return the MCP app for deployment."""
    return mcp


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    port = int(os.environ.get("PORT", "8000"))

    mcp.run(
        transport=transport,
        host="0.0.0.0",
        port=port,
    )
