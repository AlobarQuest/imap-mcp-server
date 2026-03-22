"""Account registry — discovers IMAP/SMTP accounts from environment variables."""

from __future__ import annotations

import logging
import os

from .models import AccountConfig

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("NAME", "EMAIL", "IMAP_HOST", "SMTP_HOST", "USERNAME", "PASSWORD")
OPTIONAL_DEFAULTS = {"IMAP_PORT": "993", "SMTP_PORT": "587", "SMTP_SECURITY": "starttls", "TRASH_FOLDER": "Trash"}
VALID_SMTP_SECURITY = ("starttls", "ssl")


def _validated_smtp_security(value: str, index: int) -> str:
    """Validate smtp_security value, defaulting to starttls if invalid."""
    value = value.lower().strip()
    if value not in VALID_SMTP_SECURITY:
        logger.warning(
            "Account index %d: invalid SMTP_SECURITY '%s', defaulting to 'starttls'",
            index,
            value,
        )
        return "starttls"
    return value


def _find_account_indices() -> list[int]:
    """Scan environment for all IMAP_ACCOUNT_N_NAME keys and return sorted indices."""
    indices = []
    for key in os.environ:
        if key.startswith("IMAP_ACCOUNT_") and key.endswith("_NAME"):
            middle = key[len("IMAP_ACCOUNT_"):-len("_NAME")]
            try:
                indices.append(int(middle))
            except ValueError:
                continue
    return sorted(indices)


def discover_accounts() -> dict[str, AccountConfig]:
    """Scan env vars for all IMAP_ACCOUNT_N_* patterns and return a registry keyed by name.

    Scans all matching prefixes found in the environment rather than stopping
    at the first numbering gap.
    """
    accounts: dict[str, AccountConfig] = {}

    for index in _find_account_indices():
        prefix = f"IMAP_ACCOUNT_{index}_"
        name = os.environ.get(f"{prefix}NAME")
        if name is None:
            continue

        missing = [f for f in REQUIRED_FIELDS if not os.environ.get(f"{prefix}{f}")]
        if missing:
            logger.warning(
                "Skipping account %s (index %d): missing %s",
                name,
                index,
                ", ".join(missing),
            )
            continue

        try:
            config = AccountConfig(
                name=name,
                email=os.environ[f"{prefix}EMAIL"],
                imap_host=os.environ[f"{prefix}IMAP_HOST"],
                imap_port=int(
                    os.environ.get(f"{prefix}IMAP_PORT", OPTIONAL_DEFAULTS["IMAP_PORT"])
                ),
                smtp_host=os.environ[f"{prefix}SMTP_HOST"],
                smtp_port=int(
                    os.environ.get(f"{prefix}SMTP_PORT", OPTIONAL_DEFAULTS["SMTP_PORT"])
                ),
                smtp_security=_validated_smtp_security(
                    os.environ.get(f"{prefix}SMTP_SECURITY", OPTIONAL_DEFAULTS["SMTP_SECURITY"]),
                    index,
                ),
                username=os.environ[f"{prefix}USERNAME"],
                password=os.environ[f"{prefix}PASSWORD"],
                trash_folder=os.environ.get(f"{prefix}TRASH_FOLDER", OPTIONAL_DEFAULTS["TRASH_FOLDER"]),
            )
            accounts[name] = config
            logger.info("Registered account: %s (%s)", name, config.email)
        except Exception:
            logger.warning("Skipping account index %d: invalid configuration", index)

    logger.info("Discovered %d account(s)", len(accounts))
    return accounts


class AccountRegistry:
    """Thread-safe account registry."""

    def __init__(self) -> None:
        self._accounts: dict[str, AccountConfig] = {}

    def load_from_env(self) -> None:
        self._accounts = discover_accounts()

    def get(self, name: str) -> AccountConfig | None:
        return self._accounts.get(name)

    def list_all(self) -> list[AccountConfig]:
        return list(self._accounts.values())

    def names(self) -> list[str]:
        return list(self._accounts.keys())

    def __len__(self) -> int:
        return len(self._accounts)
