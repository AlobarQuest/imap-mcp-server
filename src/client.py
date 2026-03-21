"""Async IMAP/SMTP client for email operations."""

from __future__ import annotations

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


class IMAPClient:
    """Async IMAP client wrapping aioimaplib using UID commands."""

    def __init__(self, config: AccountConfig) -> None:
        self.config = config
        self._imap: aioimaplib.IMAP4_SSL | None = None

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
            raise Exception(f"Authentication failed for {self.config.username}")

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

    async def list_folders(self) -> list[str]:
        imap = await self._ensure_connected()
        response = await imap.list("", "*")
        if response.result != "OK":
            return []
        folders = []
        for line in response.lines:
            if not line:
                continue
            # Parse LIST response: (\flags) "delimiter" "name"
            parts = line.rsplit('" ', 1)
            if len(parts) == 2:
                folder_name = parts[1].strip('"')
                folders.append(folder_name)
        return folders

    async def list_emails(
        self,
        folder: str = "INBOX",
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
        since_date: str | None = None,
        search: str | None = None,
    ) -> list[EmailSummary]:
        imap = await self._ensure_connected()
        await imap.select(folder)

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
            criteria.append(f'OR SUBJECT "{search}" FROM "{search}"')
        if not criteria:
            criteria.append("ALL")

        search_str = " ".join(criteria)
        response = await imap.uid("search", search_str)
        if response.result != "OK":
            return []

        uid_line = response.lines[0]
        if not uid_line.strip():
            return []
        uids = uid_line.split()

        # Reverse for newest first, apply pagination
        uids = list(reversed(uids))
        uids = uids[offset : offset + limit]

        results = []
        for uid in uids:
            summary = await self._fetch_summary(imap, uid)
            if summary:
                results.append(summary)
        return results

    async def _fetch_summary(
        self, imap: aioimaplib.IMAP4_SSL, uid: str
    ) -> EmailSummary | None:
        response = await imap.uid("fetch", uid, "(FLAGS BODY.PEEK[HEADER] BODY.PEEK[TEXT])")
        if response.result != "OK":
            return None

        # Parse the fetched data
        raw_data = b""
        flags_str = ""
        for line in response.lines:
            if isinstance(line, bytes):
                raw_data += line
            elif isinstance(line, str) and "FLAGS" in line:
                flags_str = line

        if not raw_data:
            return None

        try:
            msg = email.message_from_bytes(raw_data, policy=email.policy.default)
        except Exception:
            return None

        is_read = "\\Seen" in flags_str
        subject = str(msg.get("Subject", "(no subject)"))
        sender = str(msg.get("From", ""))
        date_str = str(msg.get("Date", ""))

        # Get preview from body
        body = ""
        try:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_content()
                        break
            else:
                if msg.get_content_type() == "text/plain":
                    body = msg.get_content()
        except Exception:
            body = ""

        preview = (body[:200] + "...") if len(body) > 200 else body
        preview = preview.replace("\n", " ").strip()

        has_attachments = False
        if msg.is_multipart():
            has_attachments = any(
                part.get_content_disposition() == "attachment"
                for part in msg.walk()
            )

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
        imap = await self._ensure_connected()
        await imap.select(folder)

        response = await imap.uid("fetch", uid, "(FLAGS BODY[])")
        if response.result != "OK":
            return None

        raw_data = b""
        for line in response.lines:
            if isinstance(line, bytes):
                raw_data += line

        if not raw_data:
            return None

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
        imap = await self._ensure_connected()

        if folder == "ALL":
            folders = await self.list_folders()
        else:
            folders = [folder]

        results: list[EmailSummary] = []
        for f in folders:
            if len(results) >= limit:
                break
            try:
                await imap.select(f)
                search_criteria = (
                    f'OR (OR SUBJECT "{query}" FROM "{query}") '
                    f'(OR TO "{query}" BODY "{query}")'
                )
                response = await imap.uid("search", search_criteria)
                if response.result != "OK":
                    continue

                uid_line = response.lines[0]
                if not uid_line.strip():
                    continue
                uids = list(reversed(uid_line.split()))

                for uid in uids[: limit - len(results)]:
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
        imap = await self._ensure_connected()
        await imap.select(folder)

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
        imap = await self._ensure_connected()
        await imap.select(from_folder)

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
        imap = await self._ensure_connected()
        await imap.select(folder)

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
            result = await self.move_email(uids, folder, "Trash")
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
