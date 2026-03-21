"""Tests for IMAP/SMTP client logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.client import IMAPClient, SMTPClient
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
        mock_response = MagicMock()
        mock_response.result = "OK"
        mock_imap.noop.return_value = mock_response
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
    async def test_list_folders(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = AsyncMock()

        # Mock noop for is_connected
        noop_resp = MagicMock()
        noop_resp.result = "OK"
        mock_imap.noop.return_value = noop_resp

        # Mock list response
        list_resp = MagicMock()
        list_resp.result = "OK"
        list_resp.lines = [
            '(\\HasNoChildren) "/" "INBOX"',
            '(\\HasNoChildren) "/" "Sent"',
            '(\\HasNoChildren) "/" "Trash"',
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
        mock_imap = AsyncMock()

        noop_resp = MagicMock()
        noop_resp.result = "OK"
        mock_imap.noop.return_value = noop_resp

        list_resp = MagicMock()
        list_resp.result = "NO"
        mock_imap.list.return_value = list_resp
        client._imap = mock_imap

        folders = await client.list_folders()
        assert folders == []

    @pytest.mark.asyncio
    async def test_mark_read(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = AsyncMock()

        noop_resp = MagicMock()
        noop_resp.result = "OK"
        mock_imap.noop.return_value = noop_resp

        select_resp = MagicMock()
        select_resp.result = "OK"
        mock_imap.select.return_value = select_resp

        store_resp = MagicMock()
        store_resp.result = "OK"
        mock_imap.store.return_value = store_resp
        client._imap = mock_imap

        result = await client.mark_read(["1", "2"], folder="INBOX", read=True)
        assert result.success is True
        assert result.updated_count == 2
        assert mock_imap.store.call_count == 2

    @pytest.mark.asyncio
    async def test_mark_unread(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = AsyncMock()

        noop_resp = MagicMock()
        noop_resp.result = "OK"
        mock_imap.noop.return_value = noop_resp

        select_resp = MagicMock()
        select_resp.result = "OK"
        mock_imap.select.return_value = select_resp

        store_resp = MagicMock()
        store_resp.result = "OK"
        mock_imap.store.return_value = store_resp
        client._imap = mock_imap

        result = await client.mark_read(["1"], folder="INBOX", read=False)
        assert result.success is True
        mock_imap.store.assert_called_with("1", "-FLAGS", "\\Seen")

    @pytest.mark.asyncio
    async def test_move_email(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = AsyncMock()

        noop_resp = MagicMock()
        noop_resp.result = "OK"
        mock_imap.noop.return_value = noop_resp

        select_resp = MagicMock()
        select_resp.result = "OK"
        mock_imap.select.return_value = select_resp

        copy_resp = MagicMock()
        copy_resp.result = "OK"
        mock_imap.copy.return_value = copy_resp

        store_resp = MagicMock()
        store_resp.result = "OK"
        mock_imap.store.return_value = store_resp

        expunge_resp = MagicMock()
        expunge_resp.result = "OK"
        mock_imap.expunge.return_value = expunge_resp
        client._imap = mock_imap

        result = await client.move_email(["1"], "INBOX", "Archive")
        assert result.success is True
        assert result.moved_count == 1
        mock_imap.copy.assert_called_with("1", "Archive")

    @pytest.mark.asyncio
    async def test_delete_email_to_trash(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = AsyncMock()

        noop_resp = MagicMock()
        noop_resp.result = "OK"
        mock_imap.noop.return_value = noop_resp

        select_resp = MagicMock()
        select_resp.result = "OK"
        mock_imap.select.return_value = select_resp

        copy_resp = MagicMock()
        copy_resp.result = "OK"
        mock_imap.copy.return_value = copy_resp

        store_resp = MagicMock()
        store_resp.result = "OK"
        mock_imap.store.return_value = store_resp

        expunge_resp = MagicMock()
        expunge_resp.result = "OK"
        mock_imap.expunge.return_value = expunge_resp
        client._imap = mock_imap

        result = await client.delete_email(["1"], folder="INBOX", permanent=False)
        assert result.success is True
        assert result.deleted_count == 1

    @pytest.mark.asyncio
    async def test_delete_email_permanent(self):
        client = IMAPClient(TEST_CONFIG)
        mock_imap = AsyncMock()

        noop_resp = MagicMock()
        noop_resp.result = "OK"
        mock_imap.noop.return_value = noop_resp

        select_resp = MagicMock()
        select_resp.result = "OK"
        mock_imap.select.return_value = select_resp

        store_resp = MagicMock()
        store_resp.result = "OK"
        mock_imap.store.return_value = store_resp

        expunge_resp = MagicMock()
        expunge_resp.result = "OK"
        mock_imap.expunge.return_value = expunge_resp
        client._imap = mock_imap

        result = await client.delete_email(["1", "2"], folder="INBOX", permanent=True)
        assert result.success is True
        assert result.deleted_count == 2


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
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["hostname"] == "smtp.example.com"
        assert call_kwargs.kwargs["port"] == 587
        assert call_kwargs.kwargs["start_tls"] is True

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
