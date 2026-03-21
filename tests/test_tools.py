"""Tests for MCP tool functions."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _test_env():
    """Return env vars for a single test account."""
    return {
        "IMAP_ACCOUNT_1_NAME": "testacct",
        "IMAP_ACCOUNT_1_EMAIL": "test@example.com",
        "IMAP_ACCOUNT_1_IMAP_HOST": "imap.example.com",
        "IMAP_ACCOUNT_1_IMAP_PORT": "993",
        "IMAP_ACCOUNT_1_SMTP_HOST": "smtp.example.com",
        "IMAP_ACCOUNT_1_SMTP_PORT": "587",
        "IMAP_ACCOUNT_1_USERNAME": "test@example.com",
        "IMAP_ACCOUNT_1_PASSWORD": "secret",
    }


@pytest.fixture(autouse=True)
def _setup_env():
    """Set up environment and reload server module for each test."""
    env = _test_env()
    with patch.dict(os.environ, env, clear=True):
        yield


class TestToolErrorHandling:
    """Test that tools return structured errors for invalid accounts."""

    @pytest.mark.asyncio
    async def test_list_emails_unknown_account(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            # Re-import to pick up env
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_list_emails(account="nonexistent")
            assert isinstance(result, dict)
            assert result["error"] is True
            assert result["code"] == "ACCOUNT_NOT_FOUND"
            assert "nonexistent" in result["message"]

    @pytest.mark.asyncio
    async def test_read_email_unknown_account(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_read_email(account="nope", email_id="1")
            assert result["error"] is True
            assert result["code"] == "ACCOUNT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_search_unknown_account(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_search_emails(account="nope", query="test")
            assert result["error"] is True
            assert result["code"] == "ACCOUNT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_send_unknown_account(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_send_email(
                account="nope", to=["x@x.com"], subject="Hi", body="Hello"
            )
            assert result["error"] is True
            assert result["code"] == "ACCOUNT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_mark_read_unknown_account(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_mark_read(account="nope", email_ids=["1"])
            assert result["error"] is True
            assert result["code"] == "ACCOUNT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_move_unknown_account(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_move_email(
                account="nope", email_ids=["1"], from_folder="INBOX", to_folder="Trash"
            )
            assert result["error"] is True
            assert result["code"] == "ACCOUNT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_list_folders_unknown_account(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_list_folders(account="nope")
            assert result["error"] is True
            assert result["code"] == "ACCOUNT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_unknown_account(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_delete_email(account="nope", email_ids=["1"])
            assert result["error"] is True
            assert result["code"] == "ACCOUNT_NOT_FOUND"


class TestListAccounts:
    @pytest.mark.asyncio
    async def test_list_accounts_returns_configured(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            result = await server.imap_list_accounts()
            assert isinstance(result, list)
            assert len(result) >= 1
            account = result[0]
            assert account["name"] == "testacct"
            assert account["email"] == "test@example.com"
            assert "status" in account


class TestToolsWithMockedClient:
    """Test tool functions with mocked IMAP client."""

    @pytest.mark.asyncio
    async def test_list_emails_success(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            from src.models import EmailSummary

            mock_client = AsyncMock()
            mock_client.list_emails.return_value = [
                EmailSummary(
                    id="1",
                    subject="Test Email",
                    **{"from": "sender@example.com"},
                    date="2024-01-01",
                    is_read=False,
                    has_attachments=False,
                    preview="Hello...",
                )
            ]
            server.imap_clients["testacct"] = mock_client

            result = await server.imap_list_emails(account="testacct")
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["subject"] == "Test Email"
            assert result[0]["from"] == "sender@example.com"

    @pytest.mark.asyncio
    async def test_list_emails_limits_to_100(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            mock_client = AsyncMock()
            mock_client.list_emails.return_value = []
            server.imap_clients["testacct"] = mock_client

            await server.imap_list_emails(account="testacct", limit=500)
            call_kwargs = mock_client.list_emails.call_args.kwargs
            assert call_kwargs["limit"] == 100

    @pytest.mark.asyncio
    async def test_list_folders_success(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            mock_client = AsyncMock()
            mock_client.list_folders.return_value = ["INBOX", "Sent", "Trash"]
            server.imap_clients["testacct"] = mock_client

            result = await server.imap_list_folders(account="testacct")
            assert result == ["INBOX", "Sent", "Trash"]

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            from src.models import SendResult

            mock_smtp = AsyncMock()
            mock_smtp.send_email.return_value = SendResult(
                success=True, message_id="<msg123>"
            )
            server.smtp_clients["testacct"] = mock_smtp

            result = await server.imap_send_email(
                account="testacct",
                to=["recipient@example.com"],
                subject="Hi",
                body="Hello!",
            )
            assert result["success"] is True
            assert result["message_id"] == "<msg123>"

    @pytest.mark.asyncio
    async def test_connection_error_returns_structured(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            mock_client = AsyncMock()
            mock_client.list_emails.side_effect = ConnectionError("connection timed out")
            server.imap_clients["testacct"] = mock_client

            result = await server.imap_list_emails(account="testacct")
            assert isinstance(result, dict)
            assert result["error"] is True
            assert result["code"] == "CONNECTION_TIMEOUT"
            assert result["account"] == "testacct"

    @pytest.mark.asyncio
    async def test_auth_error_returns_auth_failed(self):
        with patch.dict(os.environ, _test_env(), clear=True):
            import importlib
            from src import server
            importlib.reload(server)

            mock_client = AsyncMock()
            mock_client.list_emails.side_effect = Exception("Authentication failed")
            server.imap_clients["testacct"] = mock_client

            result = await server.imap_list_emails(account="testacct")
            assert result["error"] is True
            assert result["code"] == "AUTH_FAILED"
