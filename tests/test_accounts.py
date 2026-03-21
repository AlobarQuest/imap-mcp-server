"""Tests for account registry and discovery."""

import os
from unittest.mock import patch

import pytest

from src.accounts import AccountRegistry, discover_accounts


def _make_env(accounts: list[dict]) -> dict:
    """Build env dict for test accounts."""
    env = {}
    for i, acct in enumerate(accounts, start=1):
        prefix = f"IMAP_ACCOUNT_{i}_"
        for key, value in acct.items():
            env[f"{prefix}{key.upper()}"] = value
    return env


VALID_ACCOUNT = {
    "name": "test",
    "email": "test@example.com",
    "imap_host": "imap.example.com",
    "imap_port": "993",
    "smtp_host": "smtp.example.com",
    "smtp_port": "587",
    "username": "test@example.com",
    "password": "secret",
}

VALID_ACCOUNT_2 = {
    "name": "work",
    "email": "work@example.com",
    "imap_host": "imap.work.com",
    "imap_port": "993",
    "smtp_host": "smtp.work.com",
    "smtp_port": "587",
    "username": "work@example.com",
    "password": "workpass",
}


class TestDiscoverAccounts:
    def test_no_accounts(self):
        with patch.dict(os.environ, {}, clear=True):
            accounts = discover_accounts()
        assert accounts == {}

    def test_single_account(self):
        env = _make_env([VALID_ACCOUNT])
        with patch.dict(os.environ, env, clear=True):
            accounts = discover_accounts()
        assert len(accounts) == 1
        assert "test" in accounts
        assert accounts["test"].email == "test@example.com"
        assert accounts["test"].imap_host == "imap.example.com"
        assert accounts["test"].imap_port == 993

    def test_multiple_accounts(self):
        env = _make_env([VALID_ACCOUNT, VALID_ACCOUNT_2])
        with patch.dict(os.environ, env, clear=True):
            accounts = discover_accounts()
        assert len(accounts) == 2
        assert "test" in accounts
        assert "work" in accounts

    def test_missing_required_field_skips_account(self):
        incomplete = {k: v for k, v in VALID_ACCOUNT.items() if k != "password"}
        env = _make_env([incomplete])
        with patch.dict(os.environ, env, clear=True):
            accounts = discover_accounts()
        assert len(accounts) == 0

    def test_gap_in_numbering_stops_discovery(self):
        """Account 1 exists, account 2 missing, account 3 exists — only finds 1."""
        env = _make_env([VALID_ACCOUNT])
        # Add account 3 (skipping 2)
        env["IMAP_ACCOUNT_3_NAME"] = "extra"
        env["IMAP_ACCOUNT_3_EMAIL"] = "extra@example.com"
        with patch.dict(os.environ, env, clear=True):
            accounts = discover_accounts()
        assert len(accounts) == 1
        assert "extra" not in accounts

    def test_default_ports(self):
        acct = {k: v for k, v in VALID_ACCOUNT.items() if k not in ("imap_port", "smtp_port")}
        env = _make_env([acct])
        with patch.dict(os.environ, env, clear=True):
            accounts = discover_accounts()
        assert accounts["test"].imap_port == 993
        assert accounts["test"].smtp_port == 587


class TestAccountRegistry:
    def test_empty_registry(self):
        reg = AccountRegistry()
        assert len(reg) == 0
        assert reg.list_all() == []
        assert reg.names() == []
        assert reg.get("anything") is None

    def test_load_from_env(self):
        env = _make_env([VALID_ACCOUNT, VALID_ACCOUNT_2])
        reg = AccountRegistry()
        with patch.dict(os.environ, env, clear=True):
            reg.load_from_env()
        assert len(reg) == 2
        assert reg.get("test") is not None
        assert reg.get("work") is not None
        assert reg.get("nonexistent") is None
        assert sorted(reg.names()) == ["test", "work"]

    def test_list_all_returns_configs(self):
        env = _make_env([VALID_ACCOUNT])
        reg = AccountRegistry()
        with patch.dict(os.environ, env, clear=True):
            reg.load_from_env()
        configs = reg.list_all()
        assert len(configs) == 1
        assert configs[0].name == "test"
        assert configs[0].email == "test@example.com"
