"""Tests for IMAP/SMTP client logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.client import IMAPClient, SMTPClient, _escape_imap_string
from src.errors import AuthenticationError
from src.models import AccountConfig

TEST_CONFIG = AccountConfig(
    name="test",
    email="test@example.com",
    imap_host="imap.example.com",
    imap_port=993,
    smtp_host="smtp.example.com",
    smtp_port=587,
    username="test@example.com",
    password="secret",
)

SSL_CONFIG = AccountConfig(
    name="test-ssl",
    email="test@example.com",
    imap_host="imap.example.com",
    imap_port=993,
    smtp_host="smtp.example.com",
    smtp_port=465,
    smtp_security="ssl",
    username="test@example.com",
    password="secret",
)

CUSTOM_TRASH_CONFIG = AccountConfig(
    name="test-trash",
    email="test@example.com",
    imap_host="imap.example.com",
    imap_port=993,
    smtp_host="smtp.example.com",
    smtp_port=587,
    username="test@example.com",
    password="secret",
    trash_folder="Deleted Items",
)


def _ok_resp():
    r = MagicMock()
    r.result = "OK"
    return r


def _mock_imap_connected():
    """Return a mock IMAP with noop/select returning OK."""
    mock = AsyncMock()
    mock.noop.return_value = _ok_resp()
    mock.select.return_value = _ok_resp()
    mock.expunge.return_value = _ok_resp()
    mock.uid.return_value = _ok_resp()
    return mock


class TestIMAPClient:
    def test_init(self):
        client = IMAPClient(TEST_CONFIG)
        assert client.config == TEST_CONFIG
        assert client._imap is None

    @pytest.mark.asyncio
    async def test_is_connected_when_no_imap(self):
        client = IMAPClient(TEST_CONFIG)
        assert await client.is_connected() is False

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        client = IMAPClient(TEST_CONFIG)
        await client.disconnect()  # Should not raise

    @pytest.mark.asyncio
    async def test_is_connected_noop_ok(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = AsyncMock()
        mock_imap.noop.return_value = _ok_resp()
        client._imap = mock_imap
        assert await client.is_connected() is True

    @pytest.mark.asyncio
    async def test_is_connected_noop_fail(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = AsyncMock()
        mock_imap.noop.side_effect = Exception("connection lost")
        client._imap = mock_imap
        assert await client.is_connected() is False

    @pytest.mark.asyncio
    async def test_check_health_connects_when_disconnected(self):
        client = IMAPClient(TEST_CONFIG)
        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            async def fake_connect():
                client._imap = _mock_imap_connected()
            mock_connect.side_effect = fake_connect
            result = await client.check_health()
        assert result is True
        mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_health_returns_false_on_auth_failure(self):
        client = IMAPClient(TEST_CONFIG)
        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = AuthenticationError("bad creds", account="test")
            result = await client.check_health()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_health_already_connected(self):
        client = IMAPClient(TEST_CONFIG)
        client._imap = _mock_imap_connected()
        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            result = await client.check_health()
        assert result is True
        mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_folders(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = _mock_imap_connected()

        list_resp = MagicMock()
        list_resp.result = "OK"
        list_resp.lines = [
            b'(\\HasNoChildren) "/" INBOX',
            b'(\\HasNoChildren \\Sent) "/" Sent',
            b'(\\HasNoChildren \\Trash) "/" Trash',
        ]
        mock_imap.list.return_value = list_resp
        client._imap = mock_imap

        folders = await client.list_folders()
        assert "INBOX" in folders
        assert "Sent" in folders
        assert "Trash" in folders

    @pytest.mark.asyncio
    async def test_list_folders_failure(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = _mock_imap_connected()

        list_resp = MagicMock()
        list_resp.result = "NO"
        mock_imap.list.return_value = list_resp
        client._imap = mock_imap

        folders = await client.list_folders()
        assert folders == []

    @pytest.mark.asyncio
    async def test_read_email_uses_peek(self):
        """read_email must use BODY.PEEK[] to avoid marking as read."""
        client = IMAPClient(TEST_CONFIG)
        mock_imap = _mock_imap_connected()
        # Return empty result so it exits early
        mock_imap.uid.return_value = _ok_resp()
        mock_imap.uid.return_value.lines = []
        client._imap = mock_imap

        await client.read_email("1", folder="INBOX")
        # Verify the fetch call uses BODY.PEEK[]
        mock_imap.uid.assert_called_with("fetch", "1", "(FLAGS BODY.PEEK[])")

    @pytest.mark.asyncio
    async def test_mark_read(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = _mock_imap_connected()
        client._imap = mock_imap

        result = await client.mark_read(["1", "2"], folder="INBOX", read=True)
        assert result.success is True
        assert result.updated_count == 2
        assert mock_imap.uid.call_count == 2
        mock_imap.uid.assert_any_call("store", "1", "+FLAGS", "(\\Seen)")
        mock_imap.uid.assert_any_call("store", "2", "+FLAGS", "(\\Seen)")

    @pytest.mark.asyncio
    async def test_mark_unread(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = _mock_imap_connected()
        client._imap = mock_imap

        result = await client.mark_read(["1"], folder="INBOX", read=False)
        assert result.success is True
        mock_imap.uid.assert_called_with("store", "1", "-FLAGS", "(\\Seen)")

    @pytest.mark.asyncio
    async def test_move_email(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = _mock_imap_connected()
        client._imap = mock_imap

        result = await client.move_email(["1"], "INBOX", "Archive")
        assert result.success is True
        assert result.moved_count == 1
        mock_imap.uid.assert_any_call("copy", "1", "Archive")
        mock_imap.uid.assert_any_call("store", "1", "+FLAGS", "(\\Deleted)")

    @pytest.mark.asyncio
    async def test_delete_email_to_trash(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = _mock_imap_connected()
        client._imap = mock_imap

        result = await client.delete_email(["1"], folder="INBOX", permanent=False)
        assert result.success is True
        assert result.deleted_count == 1
        # Verify it targets the default trash folder
        mock_imap.uid.assert_any_call("copy", "1", "Trash")

    @pytest.mark.asyncio
    async def test_delete_email_custom_trash_folder(self):
        client = IMAPClient(CUSTOM_TRASH_CONFIG)
        mock_imap = _mock_imap_connected()
        client._imap = mock_imap

        result = await client.delete_email(["1"], folder="INBOX", permanent=False)
        assert result.success is True
        mock_imap.uid.assert_any_call("copy", "1", "Deleted Items")

    @pytest.mark.asyncio
    async def test_delete_email_permanent(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = _mock_imap_connected()
        client._imap = mock_imap

        result = await client.delete_email(["1", "2"], folder="INBOX", permanent=True)
        assert result.success is True
        assert result.deleted_count == 2


class TestIMAPEscaping:
    def test_normal_string(self):
        assert _escape_imap_string("hello world") == "hello world"

    def test_removes_quotes(self):
        assert _escape_imap_string('test "quoted" string') == "test quoted string"

    def test_removes_backslashes(self):
        assert _escape_imap_string("test\\value") == "testvalue"

    def test_removes_newlines(self):
        assert _escape_imap_string("line1\nline2\rline3") == "line1line2line3"

    def test_mixed_dangerous_chars(self):
        assert _escape_imap_string('a"b\\c\nd') == "abcd"

    def test_empty_string(self):
        assert _escape_imap_string("") == ""


class TestSMTPClient:
    def test_init(self):
        client = SMTPClient(TEST_CONFIG)
        assert client.config == TEST_CONFIG

    @pytest.mark.asyncio
    async def test_send_plain_text(self):
        client = SMTPClient(TEST_CONFIG)

        with patch("src.client.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "OK")
            result = await client.send_email(
                to=["recipient@example.com"],
                subject="Test",
                body="Hello world",
            )
        assert result.success is True
        assert result.message_id is not None
        assert result.message_id != ""
        assert "@" in result.message_id  # Message-ID format: <...@domain>
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["hostname"] == "smtp.example.com"
        assert call_kwargs.kwargs["port"] == 587
        assert call_kwargs.kwargs["start_tls"] is True
        assert "use_tls" not in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_send_with_ssl(self):
        client = SMTPClient(SSL_CONFIG)

        with patch("src.client.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "OK")
            result = await client.send_email(
                to=["recipient@example.com"],
                subject="Test",
                body="Hello world",
            )
        assert result.success is True
        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["use_tls"] is True
        assert "start_tls" not in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_send_html_email(self):
        client = SMTPClient(TEST_CONFIG)

        with patch("src.client.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "OK")
            result = await client.send_email(
                to=["recipient@example.com"],
                subject="Test",
                body="Hello",
                body_html="<p>Hello</p>",
            )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_with_cc_bcc(self):
        client = SMTPClient(TEST_CONFIG)

        with patch("src.client.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = ({}, "OK")
            result = await client.send_email(
                to=["to@example.com"],
                subject="Test",
                body="Hello",
                cc=["cc@example.com"],
                bcc=["bcc@example.com"],
            )
        assert result.success is True
        call_kwargs = mock_send.call_args
        recipients = call_kwargs.kwargs["recipients"]
        assert "to@example.com" in recipients
        assert "cc@example.com" in recipients
        assert "bcc@example.com" in recipients
