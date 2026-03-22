# IMAP MCP Server

Multi-account IMAP/SMTP MCP server for Claude. Connects multiple email accounts via a single deployment using FastMCP.

## Setup

### 1. Install dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure accounts

```bash
cp .env.example .env
# Edit .env with your IMAP/SMTP credentials
```

Each account is configured via numbered environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `IMAP_ACCOUNT_N_NAME` | Yes | | Short name used in tool calls |
| `IMAP_ACCOUNT_N_EMAIL` | Yes | | Email address |
| `IMAP_ACCOUNT_N_IMAP_HOST` | Yes | | IMAP server hostname |
| `IMAP_ACCOUNT_N_IMAP_PORT` | No | `993` | IMAP port |
| `IMAP_ACCOUNT_N_SMTP_HOST` | Yes | | SMTP server hostname |
| `IMAP_ACCOUNT_N_SMTP_PORT` | No | `587` | SMTP port |
| `IMAP_ACCOUNT_N_SMTP_SECURITY` | No | `starttls` | `starttls` (port 587) or `ssl` (port 465) |
| `IMAP_ACCOUNT_N_USERNAME` | Yes | | Login username |
| `IMAP_ACCOUNT_N_PASSWORD` | Yes | | Login password |
| `IMAP_ACCOUNT_N_TRASH_FOLDER` | No | `Trash` | Folder name for soft deletes |

Add as many accounts as needed by incrementing N (1, 2, 3...). Gaps in numbering are handled gracefully.

### 3. Run the server

```bash
python -m src.server
```

Starts on port 8000 with streamable-http transport by default.

### 4. Connect to Claude Desktop

Add as a remote MCP server in Claude Desktop settings:

```
https://imap-mcp.devonwatkins.com/mcp
```

Or for local development:

```json
{
  "mcpServers": {
    "imap": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `imap_list_accounts` | List all configured accounts with connection status |
| `imap_list_emails` | List emails with filters (folder, unread, date, search) |
| `imap_read_email` | Read full email content by UID (uses PEEK, does not mark as read) |
| `imap_search_emails` | Full-text search across folders |
| `imap_send_email` | Send email via SMTP (generates Message-ID) |
| `imap_mark_read` | Mark emails as read/unread |
| `imap_move_email` | Move emails between folders |
| `imap_list_folders` | List mailbox folders |
| `imap_delete_email` | Delete emails (soft: move to trash, or permanent) |

Every tool (except `imap_list_accounts`) takes an `account` parameter matching the account `NAME`.

## Health Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Combined status with per-account details |
| `GET /health/live` | Liveness probe (process is up) |
| `GET /health/ready` | Readiness probe (at least one account can authenticate) |

The readiness endpoint actively probes IMAP connectivity — it does not rely on cached state.

```json
{"status": "ready", "accounts": {"adjustright": "connected", "watkinshomesales": "connected"}}
```

## Error Handling

All tools return structured errors with stable codes:

```json
{"error": true, "code": "AUTH_FAILED", "message": "...", "account": "adjustright"}
```

Error codes: `AUTH_FAILED`, `CONNECTION_TIMEOUT`, `FOLDER_NOT_FOUND`, `EMAIL_NOT_FOUND`, `SEND_FAILED`, `ACCOUNT_NOT_FOUND`

## Docker

```bash
docker build -t imap-mcp-server .
docker run -p 8000:8000 --env-file .env imap-mcp-server
```

The Dockerfile includes `bws` CLI for fetching passwords from Bitwarden Secrets Manager at startup via `start.sh`.

## Production Deployment

Deployed on Coolify as a Flavor A app (single container, source build).

- **Domain:** `https://imap-mcp.devonwatkins.com`
- **Passwords:** Fetched from BWS at startup (`start.sh`)
- **Health check:** `/health/live` on port 8000

## Tests

```bash
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

### E2E Tests

```bash
# Read-only tests against production
python scripts/test_live.py

# Include mark/move/delete tests (restores state after)
python scripts/test_live.py --destructive

# Include send test (sends email to self)
python scripts/test_live.py --send

# Full suite
python scripts/test_live.py --destructive --send

# Test a specific account
python scripts/test_live.py --account watkinshomesales
```

## Architecture

```
src/
  server.py     — FastMCP app, 9 tool definitions, health endpoints
  client.py     — Async IMAP (aioimaplib) and SMTP (aiosmtplib) clients
  accounts.py   — Account registry from IMAP_ACCOUNT_N_* env vars
  models.py     — Pydantic models for all request/response types
  errors.py     — Typed exceptions (AuthenticationError, FolderNotFoundError, etc.)
tests/          — 59 unit tests
scripts/        — E2E test suite and debug tools
start.sh        — Entrypoint that fetches BWS secrets before starting server
```

### Key Design Decisions

- **Regular SEARCH, not UID SEARCH:** Namecheap Private Email doesn't support UID SEARCH. We use regular SEARCH for sequence numbers, then FETCH (UID) to convert to stable UIDs.
- **Per-account asyncio.Lock:** Prevents concurrent requests from corrupting IMAP folder selection state.
- **BODY.PEEK[]:** Read operations never mark emails as read.
- **Lazy connections:** IMAP connections are established on first use, not at startup. The readiness endpoint probes real connectivity.
