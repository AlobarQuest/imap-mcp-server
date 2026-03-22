#!/usr/bin/env python3
"""Debug script to see raw aioimaplib fetch response structure."""

import asyncio
import os
import ssl
import aioimaplib
from dotenv import load_dotenv

load_dotenv()


async def main():
    ctx = ssl.create_default_context()
    imap = aioimaplib.IMAP4_SSL(
        host="mail.privateemail.com",
        port=993,
        timeout=30,
        ssl_context=ctx,
    )
    await imap.wait_hello_from_server()

    user = os.environ.get("IMAP_ACCOUNT_1_USERNAME", "")
    passwd = os.environ.get("IMAP_ACCOUNT_1_PASSWORD", "")
    if not user or not passwd:
        print("Set IMAP_ACCOUNT_1_USERNAME and IMAP_ACCOUNT_1_PASSWORD")
        return

    resp = await imap.login(user, passwd)
    print(f"Login: {resp.result}")

    await imap.select("INBOX")

    # Search for a few messages
    resp = await imap.search("ALL")
    print(f"Search result: {resp.result}")
    line = resp.lines[0]
    if isinstance(line, bytes):
        line = line.decode()
    seqs = line.split()
    print(f"Found {len(seqs)} messages, last 3: {seqs[-3:]}")

    # Fetch one message to see response structure
    seq = seqs[-1]

    # First, get UID
    resp = await imap.fetch(seq, "(UID)")
    print(f"\n--- FETCH (UID) for seq {seq} ---")
    for i, line in enumerate(resp.lines):
        print(f"  line[{i}] type={type(line).__name__} val={repr(line)[:200]}")

    # Now fetch with UID FETCH
    import re
    uid = None
    for line in resp.lines:
        if isinstance(line, bytes):
            line = line.decode()
        if isinstance(line, str):
            m = re.search(r"UID\s+(\d+)", line)
            if m:
                uid = m.group(1)
    print(f"  Extracted UID: {uid}")

    if uid:
        resp = await imap.uid("fetch", uid, "(FLAGS BODY.PEEK[HEADER] BODY.PEEK[TEXT])")
        print(f"\n--- UID FETCH {uid} (FLAGS BODY.PEEK[HEADER] BODY.PEEK[TEXT]) ---")
        print(f"  result: {resp.result}")
        print(f"  num lines: {len(resp.lines)}")
        for i, line in enumerate(resp.lines):
            if isinstance(line, bytes):
                print(f"  line[{i}] BYTES len={len(line)} first100={repr(line[:100])}")
            else:
                print(f"  line[{i}] STR val={repr(line)[:200]}")

    await imap.logout()


asyncio.run(main())
