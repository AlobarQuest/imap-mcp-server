"""Async IMAP/SMTP client for email operations."""

from __future__ import annotations

import asyncio
import email
import email.policy
import email.utils
import logging
import re
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aioimaplib
import aiosmtplib

from .errors import (
    AuthenticationError,
    ConnectionError,
    EmailNotFoundError,
    FolderNotFoundError,
    SendError,
)
from .models import (
    AccountConfig,
    Attachment,
    EmailDetail,
    EmailSummary,
    SendResult,
    UpdateResult,
)

logger = logging.getLogger(__name__)

IMAP_TIMEOUT = 30
PREVIEW_BYTES = 512  # Max bytes to fetch for email preview

# Regex to extract UID from FETCH response line like "1 FETCH (UID 42 FLAGS ...)"
UID_RE = re.compile(r"UID\s+(\d+)")


def _escape_imap_string(s: str) -> str:
    """Escape a string for use in IMAP search commands.

    Removes characters that could break IMAP protocol commands.
    """
    # Remove backslashes and double quotes which break IMAP search syntax
    return s.replace("\\", "").replace('"', "").replace("\r", "").replace("\n", "")


class IMAPClient:
    """Async IMAP client wrapping aioimaplib.

    Uses regular SEARCH (not UID SEARCH) because some IMAP servers
    (e.g. Namecheap Private Email) don't support UID SEARCH.
    Uses UID FETCH/STORE/COPY for all other operations.
    """

    def __init__(self, config: AccountConfig) -> None:
        self.config = config
        self._imap: aioimaplib.IMAP4_SSL | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        ssl_context = ssl.create_default_context()
        self._imap = aioimaplib.IMAP4_SSL(
            host=self.config.imap_host,
            port=self.config.imap_port,
            timeout=IMAP_TIMEOUT,
            ssl_context=ssl_context,
        )
        await self._imap.wait_hello_from_server()
        response = await self._imap.login(self.config.username, self.config.password)
        if response.result != "OK":
            raise AuthenticationError(
                f"Authentication failed for {self.config.username}",
                account=self.config.name,
            )

    async def disconnect(self) -> None:
        if self._imap:
            try:
                await self._imap.logout()
            except Exception:
                pass
            self._imap = None

    async def is_connected(self) -> bool:
        if not self._imap:
            return False
        try:
            response = await self._imap.noop()
            return response.result == "OK"
        except Exception:
            return False

    async def _ensure_connected(self) -> aioimaplib.IMAP4_SSL:
        if not await self.is_connected():
            await self.connect()
        assert self._imap is not None
        return self._imap

    async def _select_folder(self, imap: aioimaplib.IMAP4_SSL, folder: str) -> None:
        """Select a folder, raising FolderNotFoundError on failure."""
        response = await imap.select(folder)
        if response.result != "OK":
            raise FolderNotFoundError(
                f"Folder '{folder}' not found or not selectable",
                account=self.config.name,
            )

    async def list_folders(self) -> list[str]:
        async with self._lock:
            imap = await self._ensure_connected()
            return await self._list_folders_locked(imap)

    async def _list_folders_locked(self, imap: aioimaplib.IMAP4_SSL) -> list[str]:
        response = await imap.list("", "*")
        if response.result != "OK":
            return []
        folders = []
        for line in response.lines:
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            parts = line.rsplit('" ', 1)
            if len(parts) == 2:
                folder_name = parts[1].strip('"')
                folders.append(folder_name)
        return folders

    async def _search(self, imap: aioimaplib.IMAP4_SSL, criteria: str) -> list[str]:
        """Run SEARCH (not UID SEARCH) and return sequence numbers as strings."""
        response = await imap.search(criteria)
        if response.result != "OK":
            return []
        line = response.lines[0]
        # Handle bytes or str
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        if not line.strip():
            return []
        return line.split()

    async def _seq_to_uids(self, imap: aioimaplib.IMAP4_SSL, seqs: list[str]) -> list[str]:
        """Convert sequence numbers to UIDs via FETCH."""
        if not seqs:
            return []
        # Ensure all seqs are strings
        seq_set = ",".join(str(s) for s in seqs)
        response = await imap.fetch(seq_set, "(UID)")
        if response.result != "OK":
            return []
        uids = []
        for line in response.lines:
            # Handle both bytes and str
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            if isinstance(line, str):
                m = UID_RE.search(line)
                if m:
                    uids.append(m.group(1))
        return uids

    async def list_emails(
        self,
        folder: str = "INBOX",
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
        since_date: str | None = None,
        search: str | None = None,
    ) -> list[EmailSummary]:
        async with self._lock:
            imap = await self._ensure_connected()
            await self._select_folder(imap, folder)

            # Build IMAP search criteria
            criteria = []
            if unread_only:
                criteria.append("UNSEEN")
            if since_date:
                try:
                    dt = datetime.fromisoformat(since_date)
                    criteria.append(f'SINCE {dt.strftime("%d-%b-%Y")}')
                except ValueError:
                    pass
            if search:
                safe = _escape_imap_string(search)
                criteria.append(f'OR SUBJECT "{safe}" FROM "{safe}"')
            if not criteria:
                criteria.append("ALL")

            search_str = " ".join(criteria)
            seqs = await self._search(imap, search_str)

            # Reverse for newest first, apply pagination
            seqs = list(reversed(seqs))
            seqs = seqs[offset : offset + limit]

            # Convert to UIDs
            uids = await self._seq_to_uids(imap, seqs)

            results = []
            for uid in uids:
                summary = await self._fetch_summary(imap, uid)
                if summary:
                    results.append(summary)
            return results

    async def _fetch_summary(
        self, imap: aioimaplib.IMAP4_SSL, uid: str
    ) -> EmailSummary | None:
        # Fetch only flags and headers — no body, for performance
        response = await imap.uid("fetch", uid, "(FLAGS BODY.PEEK[HEADER])")
        if response.result != "OK":
            return None

        flags_str = ""
        header_data = b""

        for line in response.lines:
            if isinstance(line, bytes):
                decoded = line.decode("utf-8", errors="replace")
                if "FLAGS" in decoded:
                    flags_str = decoded
            elif isinstance(line, (str, bytearray)):
                if not header_data:
                    header_data = bytes(line, "utf-8") if isinstance(line, str) else bytes(line)

        if not header_data:
            return None

        try:
            msg = email.message_from_bytes(header_data, policy=email.policy.default)
        except Exception:
            return None

        is_read = "\\Seen" in flags_str
        subject = str(msg.get("Subject", "(no subject)"))
        sender = str(msg.get("From", ""))
        date_str = str(msg.get("Date", ""))

        # Use Subject as preview since we don't fetch body for listings
        preview = subject[:200]

        # Check Content-Type header for multipart/mixed as attachment hint
        content_type = str(msg.get("Content-Type", ""))
        has_attachments = "multipart/mixed" in content_type.lower()

        return EmailSummary(
            id=uid,
            subject=subject,
            **{"from": sender},
            date=date_str,
            is_read=is_read,
            has_attachments=has_attachments,
            preview=preview,
        )

    async def read_email(self, uid: str, folder: str = "INBOX") -> EmailDetail | None:
        async with self._lock:
            return await self._read_email_locked(uid, folder)

    async def _read_email_locked(self, uid: str, folder: str) -> EmailDetail | None:
        imap = await self._ensure_connected()
        await self._select_folder(imap, folder)

        response = await imap.uid("fetch", uid, "(FLAGS BODY[])")
        if response.result != "OK":
            return None

        # Collect all content lines (str/bytearray) — these contain the full email
        raw_parts = []
        for line in response.lines:
            if isinstance(line, (str, bytearray)):
                if isinstance(line, str):
                    raw_parts.append(line.encode("utf-8"))
                else:
                    raw_parts.append(bytes(line))

        if not raw_parts:
            return None

        raw_data = b"\r\n".join(raw_parts)

        try:
            msg = email.message_from_bytes(raw_data, policy=email.policy.default)
        except Exception:
            return None

        subject = str(msg.get("Subject", "(no subject)"))
        sender = str(msg.get("From", ""))
        to_addrs = [addr.strip() for addr in str(msg.get("To", "")).split(",") if addr.strip()]
        cc_addrs = [addr.strip() for addr in str(msg.get("Cc", "")).split(",") if addr.strip()]
        date_str = str(msg.get("Date", ""))

        body_text = ""
        body_html = ""
        attachments: list[Attachment] = []

        try:
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    disposition = part.get_content_disposition()

                    if disposition == "attachment":
                        try:
                            content = part.get_content()
                            size = len(content) if hasattr(content, '__len__') else 0
                        except Exception:
                            size = 0
                        attachments.append(
                            Attachment(
                                filename=part.get_filename() or "unnamed",
                                size=size,
                                content_type=content_type,
                            )
                        )
                    elif content_type == "text/plain" and not body_text:
                        body_text = part.get_content()
                    elif content_type == "text/html" and not body_html:
                        body_html = part.get_content()
            else:
                content_type = msg.get_content_type()
                content = msg.get_content()
                if content_type == "text/plain":
                    body_text = content
                elif content_type == "text/html":
                    body_html = content
        except Exception:
            pass

        return EmailDetail(
            id=uid,
            subject=subject,
            **{"from": sender},
            to=to_addrs,
            cc=cc_addrs,
            date=date_str,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
        )

    async def search_emails(
        self, query: str, folder: str = "INBOX", limit: int = 20
    ) -> list[EmailSummary]:
        async with self._lock:
            imap = await self._ensure_connected()

            if folder == "ALL":
                folders = await self._list_folders_locked(imap)
            else:
                folders = [folder]

            results: list[EmailSummary] = []
            for f in folders:
                if len(results) >= limit:
                    break
                try:
                    await self._select_folder(imap, f)
                    safe = _escape_imap_string(query)
                    search_criteria = (
                        f'OR (OR SUBJECT "{safe}" FROM "{safe}") '
                        f'(OR TO "{safe}" BODY "{safe}")'
                    )
                    seqs = await self._search(imap, search_criteria)
                    seqs = list(reversed(seqs))
                    uids = await self._seq_to_uids(imap, seqs[: limit - len(results)])

                    for uid in uids:
                        summary = await self._fetch_summary(imap, uid)
                        if summary:
                            results.append(summary)
                except Exception:
                    logger.warning("Search failed in folder %s", f)
                    continue

            return results[:limit]

    async def mark_read(
        self,
        uids: list[str],
        folder: str = "INBOX",
        read: bool = True,
    ) -> UpdateResult:
        async with self._lock:
            imap = await self._ensure_connected()
            await self._select_folder(imap, folder)

            count = 0
            for uid in uids:
                flag_op = "+FLAGS" if read else "-FLAGS"
                response = await imap.uid("store", uid, flag_op, "(\\Seen)")
                if response.result == "OK":
                    count += 1

            return UpdateResult(success=count > 0, updated_count=count)

    async def move_email(
        self,
        uids: list[str],
        from_folder: str,
        to_folder: str,
    ) -> UpdateResult:
        async with self._lock:
            return await self._move_email_locked(uids, from_folder, to_folder)

    async def _move_email_locked(
        self,
        uids: list[str],
        from_folder: str,
        to_folder: str,
    ) -> UpdateResult:
        imap = await self._ensure_connected()
        await self._select_folder(imap, from_folder)

        count = 0
        for uid in uids:
            response = await imap.uid("copy", uid, to_folder)
            if response.result == "OK":
                await imap.uid("store", uid, "+FLAGS", "(\\Deleted)")
                count += 1

        if count > 0:
            await imap.expunge()

        return UpdateResult(success=count > 0, moved_count=count)

    async def delete_email(
        self,
        uids: list[str],
        folder: str = "INBOX",
        permanent: bool = False,
    ) -> UpdateResult:
        async with self._lock:
            imap = await self._ensure_connected()
            await self._select_folder(imap, folder)

            if permanent:
                count = 0
                for uid in uids:
                    response = await imap.uid("store", uid, "+FLAGS", "(\\Deleted)")
                    if response.result == "OK":
                        count += 1
                if count > 0:
                    await imap.expunge()
                return UpdateResult(success=count > 0, deleted_count=count)
            else:
                result = await self._move_email_locked(uids, folder, "Trash")
                return UpdateResult(success=result.success, deleted_count=result.moved_count)


class SMTPClient:
    """Async SMTP client wrapping aiosmtplib."""

    def __init__(self, config: AccountConfig) -> None:
        self.config = config

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> SendResult:
        if body_html:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(body_html, "html"))
        else:
            msg = MIMEText(body, "plain")

        msg["From"] = self.config.email
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = ", ".join(cc)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to

        all_recipients = list(to)
        if cc:
            all_recipients.extend(cc)
        if bcc:
            all_recipients.extend(bcc)

        await aiosmtplib.send(
            msg,
            hostname=self.config.smtp_host,
            port=self.config.smtp_port,
            username=self.config.username,
            password=self.config.password,
            start_tls=True,
            recipients=all_recipients,
        )

        message_id = msg.get("Message-ID", "")
        return SendResult(success=True, message_id=message_id)
