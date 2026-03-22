#!/usr/bin/env python3
"""E2E test suite for IMAP MCP server.

Tests all 9 tools against a running server instance.

Usage:
  python scripts/test_live.py                          # read-only tests
  python scripts/test_live.py --destructive            # + mark_read, move, delete
  python scripts/test_live.py --send                   # + send_email
  python scripts/test_live.py --destructive --send     # full suite
  python scripts/test_live.py --url http://localhost:8000/mcp  # test local
"""

import argparse
import asyncio
import json
import sys

import httpx

DEFAULT_URL = "https://imap-mcp.devonwatkins.com/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class MCPClient:
    def __init__(self, url: str):
        self.url = url
        self.client = httpx.AsyncClient(timeout=30)
        self.session_id = None

    async def initialize(self):
        resp = await self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-cli", "version": "1.0"},
        })
        print(f"  Server: {resp.get('serverInfo', {}).get('name', '?')}")
        await self._notify("notifications/initialized", {})
        return resp

    async def call_tool(self, name: str, arguments: dict | None = None):
        return await self._send("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })

    async def list_tools(self):
        return await self._send("tools/list", {})

    async def _send(self, method: str, params: dict) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": method,
        }
        headers = dict(HEADERS)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        resp = await self.client.post(self.url, json=payload, headers=headers)

        if "mcp-session-id" in resp.headers:
            self.session_id = resp.headers["mcp-session-id"]

        text = resp.text
        for line in text.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if "result" in data:
                    return data["result"]
                if "error" in data:
                    return {"error": data["error"]}
        return {"error": f"Unexpected response: {text[:200]}"}

    async def _notify(self, method: str, params: dict):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        headers = dict(HEADERS)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        await self.client.post(self.url, json=payload, headers=headers)

    async def close(self):
        await self.client.aclose()


def parse_tool_result(result) -> tuple[object, bool]:
    """Extract parsed data and error status from a tool result.

    Returns (parsed_data, is_error).
    """
    if isinstance(result, dict) and "content" in result:
        for item in result["content"]:
            if item.get("type") == "text":
                try:
                    parsed = json.loads(item["text"])
                    is_error = isinstance(parsed, dict) and parsed.get("error", False)
                    return parsed, is_error
                except json.JSONDecodeError:
                    return item["text"], False
    # FastMCP may return structuredContent for simple types
    if isinstance(result, dict) and "structuredContent" in result:
        sc = result["structuredContent"]
        data = sc.get("result", sc)
        is_error = result.get("isError", False)
        return data, is_error
    if isinstance(result, dict) and "error" in result:
        return result, True
    return result, False


def print_result(result):
    """Pretty print a tool result."""
    data, _ = parse_tool_result(result)
    print(f"  {json.dumps(data, indent=2, default=str)[:600]}")


class TestRunner:
    def __init__(self, client: MCPClient):
        self.client = client
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.total = 0

    async def test(
        self,
        name: str,
        tool: str,
        args: dict | None = None,
        expect_error: bool = False,
        validate: callable = None,
    ) -> object:
        """Run a single tool test. Returns parsed result data."""
        self.total += 1
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"Tool: {tool}({json.dumps(args or {})})")
        print(f"{'='*60}")
        try:
            result = await self.client.call_tool(tool, args)
            print_result(result)

            data, is_error = parse_tool_result(result)

            if expect_error and is_error:
                print(f"  PASS (expected error)")
                self.passed += 1
            elif not expect_error and not is_error:
                if validate:
                    try:
                        validate(data)
                        print(f"  PASS")
                        self.passed += 1
                    except AssertionError as e:
                        print(f"  FAIL (validation: {e})")
                        self.failed += 1
                else:
                    print(f"  PASS")
                    self.passed += 1
            elif expect_error and not is_error:
                print(f"  FAIL (expected error but got success)")
                self.failed += 1
            else:
                print(f"  FAIL (unexpected error)")
                self.failed += 1

            return data
        except Exception as e:
            print(f"  FAIL: {e}")
            self.failed += 1
            return None

    def skip(self, name: str, reason: str):
        self.skipped += 1
        print(f"\n{'='*60}")
        print(f"SKIP: {name} ({reason})")
        print(f"{'='*60}")

    def summary(self) -> bool:
        print(f"\n{'='*60}")
        parts = [f"{self.passed}/{self.total} passed"]
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        print(f"  RESULTS: {', '.join(parts)}")
        print(f"{'='*60}\n")
        return self.failed == 0


async def run_tests(url: str, account: str, destructive: bool, send: bool):
    client = MCPClient(url)
    t = TestRunner(client)

    # --- Connect ---
    print(f"\nConnecting to {url}...")
    try:
        await client.initialize()
        print("  Connected\n")
    except Exception as e:
        print(f"  Failed to connect: {e}")
        await client.close()
        return False

    tools = await client.list_tools()
    tool_names = [x["name"] for x in tools.get("tools", [])]
    print(f"Tools: {', '.join(tool_names)}\n")

    # =========================================================
    # READ-ONLY TESTS (always run)
    # =========================================================

    # 1. List accounts
    accounts = await t.test(
        "List accounts",
        "imap_list_accounts",
        validate=lambda d: (
            assert_(isinstance(d, list), "expected list"),
            assert_(len(d) >= 1, "expected at least 1 account"),
            assert_(all("name" in a and "email" in a for a in d), "missing fields"),
        ),
    )

    # 2. List folders
    folders = await t.test(
        "List folders",
        "imap_list_folders",
        {"account": account},
        validate=lambda d: (
            assert_(isinstance(d, list), "expected list"),
            assert_(len(d) >= 1, "expected at least 1 folder"),
        ),
    )

    # 3. List emails
    emails = await t.test(
        "List emails (default, limit 5)",
        "imap_list_emails",
        {"account": account, "limit": 5},
        validate=lambda d: (
            assert_(isinstance(d, list), "expected list"),
            assert_(len(d) >= 1, "expected at least 1 email"),
            assert_(all(e.get("subject") for e in d), "emails missing subject"),
            assert_(all(e.get("id") for e in d), "emails missing id"),
            assert_(all(e.get("from") for e in d), "emails missing from"),
            assert_(all(e.get("date") for e in d), "emails missing date"),
        ),
    )

    # 4. List emails (unread)
    await t.test(
        "List emails (unread only)",
        "imap_list_emails",
        {"account": account, "unread_only": True, "limit": 5},
    )

    # 5. Read a specific email (use first email from listing)
    email_id = None
    if isinstance(emails, list) and len(emails) > 0:
        email_id = emails[0].get("id")

    if email_id:
        await t.test(
            f"Read email (UID {email_id})",
            "imap_read_email",
            {"account": account, "email_id": email_id},
            validate=lambda d: (
                assert_(isinstance(d, dict), "expected dict"),
                assert_(d.get("subject"), "missing subject"),
                assert_(d.get("from"), "missing from"),
                assert_(d.get("to"), "missing to"),
                assert_(
                    d.get("body_text") or d.get("body_html"),
                    "missing both body_text and body_html",
                ),
            ),
        )
    else:
        t.skip("Read email", "no emails found to read")

    # 6. Search
    await t.test(
        "Search emails",
        "imap_search_emails",
        {"account": account, "query": "test", "limit": 3},
    )

    # 7. Error: unknown account
    await t.test(
        "Error: unknown account",
        "imap_list_emails",
        {"account": "nonexistent"},
        expect_error=True,
    )

    # 8. Error: unknown account (folders)
    await t.test(
        "Error: unknown account (folders)",
        "imap_list_folders",
        {"account": "nonexistent"},
        expect_error=True,
    )

    # =========================================================
    # DESTRUCTIVE TESTS (require --destructive)
    # =========================================================

    if destructive and email_id:
        # 9. Mark read
        await t.test(
            f"Mark email read (UID {email_id})",
            "imap_mark_read",
            {"account": account, "email_ids": [email_id], "read": True},
            validate=lambda d: (
                assert_(d.get("success") is True, "mark_read failed"),
                assert_(d.get("updated_count", 0) >= 1, "no emails updated"),
            ),
        )

        # 10. Mark unread (restore)
        await t.test(
            f"Mark email unread (UID {email_id}, restore)",
            "imap_mark_read",
            {"account": account, "email_ids": [email_id], "read": False},
            validate=lambda d: (
                assert_(d.get("success") is True, "mark_unread failed"),
            ),
        )

        # 11. Move to Trash and back
        await t.test(
            f"Move email to Trash (UID {email_id})",
            "imap_move_email",
            {
                "account": account,
                "email_ids": [email_id],
                "from_folder": "INBOX",
                "to_folder": "Trash",
            },
            validate=lambda d: (
                assert_(d.get("success") is True, "move failed"),
                assert_(d.get("moved_count", 0) >= 1, "no emails moved"),
            ),
        )

        # Move back from Trash to INBOX
        # Note: UID may change after move on some servers, so we search for it
        await t.test(
            "Move email back from Trash to INBOX",
            "imap_move_email",
            {
                "account": account,
                "email_ids": [email_id],
                "from_folder": "Trash",
                "to_folder": "INBOX",
            },
        )

        # 12. Delete (soft — move to Trash)
        # Use a different email to avoid conflicts
        second_id = None
        if isinstance(emails, list) and len(emails) > 1:
            second_id = emails[1].get("id")

        if second_id:
            await t.test(
                f"Delete email (soft, UID {second_id})",
                "imap_delete_email",
                {"account": account, "email_ids": [second_id]},
                validate=lambda d: (
                    assert_(d.get("success") is True, "delete failed"),
                    assert_(d.get("deleted_count", 0) >= 1, "no emails deleted"),
                ),
            )

            # Restore: move back from Trash
            await t.test(
                "Restore deleted email from Trash",
                "imap_move_email",
                {
                    "account": account,
                    "email_ids": [second_id],
                    "from_folder": "Trash",
                    "to_folder": "INBOX",
                },
            )
        else:
            t.skip("Delete email (soft)", "not enough emails for safe test")

    elif destructive and not email_id:
        t.skip("Destructive tests", "no emails found")
    else:
        t.skip("Mark read/unread", "requires --destructive")
        t.skip("Move email", "requires --destructive")
        t.skip("Delete email", "requires --destructive")

    # =========================================================
    # SEND TEST (requires --send)
    # =========================================================

    if send:
        # Get the account email to send to self
        account_email = None
        if isinstance(accounts, list):
            for a in accounts:
                if a.get("name") == account:
                    account_email = a.get("email")
                    break

        if account_email:
            await t.test(
                f"Send test email (to self: {account_email})",
                "imap_send_email",
                {
                    "account": account,
                    "to": [account_email],
                    "subject": "[TEST] IMAP MCP E2E test",
                    "body": "This is an automated test email from the IMAP MCP E2E suite. Safe to delete.",
                },
                validate=lambda d: (
                    assert_(d.get("success") is True, "send failed"),
                ),
            )
        else:
            t.skip("Send email", f"could not find email for account '{account}'")
    else:
        t.skip("Send email", "requires --send")

    # --- Summary ---
    success = t.summary()
    await client.close()
    return success


def assert_(condition, msg=""):
    """Assertion helper for use in validate lambdas."""
    if not condition:
        raise AssertionError(msg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="E2E test suite for IMAP MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/test_live.py                          # read-only tests
  python scripts/test_live.py --destructive            # + mark, move, delete
  python scripts/test_live.py --send                   # + send email
  python scripts/test_live.py --destructive --send     # full suite
  python scripts/test_live.py --account watkinshomesales  # test different account
""",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"MCP server URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--account",
        default="adjustright",
        help="Account name to test (default: adjustright)",
    )
    parser.add_argument(
        "--destructive",
        action="store_true",
        help="Enable destructive tests (mark_read, move, delete). Restores state after.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Enable send_email test (sends a test email to the account's own address).",
    )
    args = parser.parse_args()

    if args.destructive:
        print("WARNING: Destructive tests enabled (mark, move, delete)")
    if args.send:
        print("WARNING: Send test enabled (will send an email)")

    success = asyncio.run(run_tests(args.url, args.account, args.destructive, args.send))
    sys.exit(0 if success else 1)
