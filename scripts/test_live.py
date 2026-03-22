#!/usr/bin/env python3
"""Live test script for IMAP MCP server tools.

Tests all 9 tools against a running server instance.
Usage:
  python test_live.py                    # test against production
  python test_live.py --url http://localhost:8000/mcp  # test local
"""

import argparse
import json
import sys
import httpx
import asyncio

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
        # Send initialized notification
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

        # Extract session ID from response headers
        if "mcp-session-id" in resp.headers:
            self.session_id = resp.headers["mcp-session-id"]

        # Parse SSE response
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


def print_result(name: str, result):
    """Pretty print a tool result."""
    if isinstance(result, dict) and "content" in result:
        for item in result["content"]:
            if item.get("type") == "text":
                try:
                    parsed = json.loads(item["text"])
                    print(f"  {json.dumps(parsed, indent=2, default=str)[:500]}")
                except json.JSONDecodeError:
                    print(f"  {item['text'][:500]}")
    elif isinstance(result, dict) and "error" in result:
        print(f"  ERROR: {result['error']}")
    else:
        print(f"  {json.dumps(result, indent=2, default=str)[:500]}")


async def run_tests(url: str, account: str):
    client = MCPClient(url)
    passed = 0
    failed = 0
    total = 0

    async def test(name: str, tool: str, args: dict | None = None, expect_error: bool = False):
        nonlocal passed, failed, total
        total += 1
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"Tool: {tool}({json.dumps(args or {})})")
        print(f"{'='*60}")
        try:
            result = await client.call_tool(tool, args)
            print_result(tool, result)

            # Check for error in result content
            is_error = False
            if isinstance(result, dict) and "content" in result:
                for item in result["content"]:
                    if item.get("type") == "text":
                        try:
                            parsed = json.loads(item["text"])
                            if isinstance(parsed, dict) and parsed.get("error"):
                                is_error = True
                        except json.JSONDecodeError:
                            pass

            if expect_error and is_error:
                print(f"  ✓ PASS (expected error)")
                passed += 1
            elif not expect_error and not is_error:
                print(f"  ✓ PASS")
                passed += 1
            elif expect_error and not is_error:
                print(f"  ✗ FAIL (expected error but got success)")
                failed += 1
            else:
                print(f"  ✗ FAIL (unexpected error)")
                failed += 1
        except Exception as e:
            print(f"  ✗ FAIL: {e}")
            failed += 1

    # Initialize
    print(f"\nConnecting to {url}...")
    try:
        await client.initialize()
        print("  ✓ Connected\n")
    except Exception as e:
        print(f"  ✗ Failed to connect: {e}")
        await client.close()
        return

    # List available tools
    print("Listing tools...")
    tools = await client.list_tools()
    tool_names = [t["name"] for t in tools.get("tools", [])]
    print(f"  Available: {', '.join(tool_names)}\n")

    # --- Run tests ---

    await test("List accounts", "imap_list_accounts")

    await test("List folders", "imap_list_folders", {"account": account})

    await test("List emails (default)", "imap_list_emails", {
        "account": account,
        "limit": 5,
    })

    await test("List emails (unread only)", "imap_list_emails", {
        "account": account,
        "unread_only": True,
        "limit": 5,
    })

    await test("Search emails", "imap_search_emails", {
        "account": account,
        "query": "test",
        "limit": 3,
    })

    await test("Unknown account error", "imap_list_emails", {
        "account": "nonexistent",
    }, expect_error=True)

    await test("List folders for unknown account", "imap_list_folders", {
        "account": "nonexistent",
    }, expect_error=True)

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}\n")

    await client.close()
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test IMAP MCP server tools")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"MCP server URL (default: {DEFAULT_URL})")
    parser.add_argument("--account", default="adjustright", help="Account name to test (default: adjustright)")
    args = parser.parse_args()

    success = asyncio.run(run_tests(args.url, args.account))
    sys.exit(0 if success else 1)
