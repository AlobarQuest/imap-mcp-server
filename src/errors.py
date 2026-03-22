"""Typed exceptions for IMAP operations."""


class IMAPError(Exception):
    """Base IMAP error."""

    code: str = "IMAP_ERROR"

    def __init__(self, message: str, account: str | None = None):
        self.account = account
        super().__init__(message)


class AuthenticationError(IMAPError):
    code = "AUTH_FAILED"


class ConnectionError(IMAPError):
    code = "CONNECTION_TIMEOUT"


class FolderNotFoundError(IMAPError):
    code = "FOLDER_NOT_FOUND"


class EmailNotFoundError(IMAPError):
    code = "EMAIL_NOT_FOUND"


class SendError(IMAPError):
    code = "SEND_FAILED"


class AccountNotFoundError(IMAPError):
    code = "ACCOUNT_NOT_FOUND"
