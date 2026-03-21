"""Account registry — discovers IMAP/SMTP accounts from environment variables."""

from __future__ import annotations

import logging
import os

from .models import AccountConfig

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("NAME", "EMAIL", "IMAP_HOST", "SMTP_HOST", "USERNAME", "PASSWORD")
OPTIONAL_DEFAULTS = {"IMAP_PORT": "993", "SMTP_PORT": "587"}


def discover_accounts() -> dict[str, AccountConfig]:
    """Scan env vars for IMAP_ACCOUNT_N_* patterns and return a registry keyed by name."""
    accounts: dict[str, AccountConfig] = {}
    index = 1

    while True:
        prefix = f"IMAP_ACCOUNT_{index}_"
        name = os.environ.get(f"{prefix}NAME")
        if name is None:
            break

        missing = [f for f in REQUIRED_FIELDS if not os.environ.get(f"{prefix}{f}")]
        if missing:
            logger.warning(
                "Skipping account %s (index %d): missing %s",
                name,
                index,
                ", ".join(missing),
            )
            index += 1
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
                username=os.environ[f"{prefix}USERNAME"],
                password=os.environ[f"{prefix}PASSWORD"],
            )
            accounts[name] = config
            logger.info("Registered account: %s (%s)", name, config.email)
        except Exception:
            logger.warning("Skipping account index %d: invalid configuration", index)

        index += 1

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
