#!/usr/bin/env python3
"""Create an API key for the hosted MobiData BW MCP server.

Prints the key once and stores only its SHA-256 hash as `name:hash` in the key file.
Standard library only, so it runs on the server without installing the package.

    sudo python3 deploy/new-api-key.py alice
    sudo python3 deploy/new-api-key.py alice --file /etc/mobidata-mcp/keys
"""

import argparse
import hashlib
import os
import re
import secrets
import shutil
import sys
from pathlib import Path

NAME = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="label for the key holder, e.g. alice (letters, digits, _.-)")
    parser.add_argument("--file", default="/etc/mobidata-mcp/keys", type=Path)
    parser.add_argument(
        "--owner",
        default="10001",
        help="user that reads the file when run as root: a name (systemd: mobidata-mcp) or uid",
    )
    args = parser.parse_args()

    if not NAME.match(args.name):
        print("Name must be 1-32 characters of letters, digits, '_', '.' or '-'.", file=sys.stderr)
        return 2

    path: Path = args.file
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if any(line.partition(":")[0] == args.name for line in existing):
        print(f"A key named {args.name!r} already exists. Pick another name.", file=sys.stderr)
        return 1

    token = "mdbw_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(f"{args.name}:{digest}\n")
    os.chmod(path, 0o600)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        owner = int(args.owner) if args.owner.isdigit() else args.owner
        shutil.chown(path, user=owner, group=owner)

    print(token)
    print(f"Key for {args.name!r} added. Shown once; it cannot be recovered.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
