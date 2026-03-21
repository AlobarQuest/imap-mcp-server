# IMAP MCP Server

Multi-account IMAP/SMTP MCP server for Claude. Connects multiple email accounts via a single deployment using the FastMCP framework.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure accounts

```bash
cp .env.example .env
# Edit .env with your IMAP/SMTP credentials
```

Each account is configured via numbered environment variables:

| Variable | Description |
|----------|-------------|
| `IMAP_ACCOUNT_N_NAME` | Short name for the account (used in tool calls) |
| `IMAP_ACCOUNT_N_EMAIL` | Email address |
| `IMAP_ACCOUNT_N_IMAP_HOST` | IMAP server hostname |
| `IMAP_ACCOUNT_N_IMAP_PORT` | IMAP port (default: 993) |
| `IMAP_ACCOUNT_N_SMTP_HOST` | SMTP server hostname |
| `IMAP_ACCOUNT_N_SMTP_PORT` | SMTP port (default: 587) |
| `IMAP_ACCOUNT_N_USERNAME` | Login username |
| `IMAP_ACCOUNT_N_PASSWORD` | Login password |

Add as many accounts as needed by incrementing N (1, 2, 3...).

### 3. Run the server

```bash
python -m src.server
```

The server starts on port 8000 with streamable-http transport by default.

### 4. Connect to Claude

Add to your Claude MCP config:

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
| `imap_list_accounts` | List all configured accounts and their status |
| `imap_list_emails` | List emails with filters (folder, unread, date, search) |
| `imap_read_email` | Read full email content by UID |
| `imap_search_emails` | Full-text search across folders |
| `imap_send_email` | Send email via SMTP |
| `imap_mark_read` | Mark emails as read/unread |
| `imap_move_email` | Move emails between folders |
| `imap_list_folders` | List mailbox folders |
| `imap_delete_email` | Delete emails (trash or permanent) |

Every tool (except `imap_list_accounts`) takes an `account` parameter matching the account `NAME`.

## Health Check

```
GET /health
```

Returns per-account connection status:

```json
{"status": "ok", "accounts": {"adjustright": "connected", "watkinshomesales": "connected"}}
```

## Docker

```bash
docker build -t imap-mcp-server .
docker run -p 8000:8000 --env-file .env imap-mcp-server
```

## Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```
