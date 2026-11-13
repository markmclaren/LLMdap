"""llmdap lookup <name> — show what a logical service name resolves to."""
import argparse
import json
import os
import sys
from typing import List, Optional

from .client import CLASSIFICATION_ORDER, LLMDAPClient, LLMDAPError


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(prog="llmdap", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    look = sub.add_parser("lookup", help="Resolve a logical service name")
    look.add_argument("name")
    look.add_argument("-d", "--directory", action="append",
                      help="Directory path, file:// or https:// URL (repeatable; default $LLMDAP_DIRECTORIES "
                           "or ~/.config/llmdap/directory.json)")
    look.add_argument("-c", "--classification", choices=list(CLASSIFICATION_ORDER))
    look.add_argument("--json", action="store_true", help="Print JSON (never includes the credential)")
    args = p.parse_args(argv)

    env_dirs = [d for d in os.getenv("LLMDAP_DIRECTORIES", "").split(",") if d]
    client = LLMDAPClient(args.directory or env_dirs or None)
    try:
        r = client.lookup(args.name, required_classification=args.classification)
    except LLMDAPError as exc:
        print(f"lookup failed: {exc}", file=sys.stderr)
        sys.exit(1)

    info = {"name": r.name, "endpoint": r.endpoint, "dialect": r.dialect, "model": r.model,
            "classification": r.classification, "credential": "yes" if r.api_key else "none"}
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        for key, value in info.items():
            print(f"{key + ':':<16}{value}")
    sys.exit(0)


if __name__ == "__main__":
    main()
