#!/usr/bin/env python3
"""LLMDAP demo: look up a service name, then call the model directly.

    python examples/demo.py --list
    python examples/demo.py "Explain LDAP in one sentence"
    python examples/demo.py -s chat-gemini "Hello"
    python examples/demo.py -c restricted "Sensitive prompt"

Without -s it tries each service in DEFAULT_ORDER and uses the first that works.
Standard library only; no install needed.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "clients" / "python" / "src"))

from llmdap import CLASSIFICATION_ORDER, LLMDAPClient, LLMDAPError  # noqa: E402

DEFAULT_ORDER = ["chat-local", "chat-github", "chat-gemini", "reasoning-premium"]


def post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc


def chat(t, prompt):
    """The 'dialect' field tells us which request shape the endpoint expects."""
    base, msgs = t.endpoint.rstrip("/"), [{"role": "user", "content": prompt}]
    if t.dialect == "openai-chat":
        return post(f"{base}/chat/completions", {"model": t.model, "messages": msgs},
                    t.headers)["choices"][0]["message"]["content"]
    if t.dialect == "ollama":
        return post(f"{base}/api/chat", {"model": t.model, "messages": msgs, "stream": False},
                    t.headers)["message"]["content"]
    if t.dialect == "anthropic-messages":
        data = post(f"{base}/messages", {"model": t.model, "max_tokens": 1024, "messages": msgs},
                    {"anthropic-version": "2023-06-01", **t.headers})
        return "".join(block.get("text", "") for block in data["content"])
    raise RuntimeError(f"no adapter for dialect '{t.dialect}'")


def local_endpoint_down(t):
    """Skip a stopped Ollama quickly instead of waiting for a timeout."""
    if t.dialect != "ollama":
        return False
    try:
        urllib.request.urlopen(t.endpoint.rstrip("/") + "/api/tags", timeout=2).close()
        return False
    except Exception:
        return True


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("prompt", nargs="?", default="In one sentence, what problem does LDAP solve?")
    p.add_argument("-s", "--service", action="append", help="service name (repeatable, tried in order)")
    p.add_argument("-c", "--classification", choices=list(CLASSIFICATION_ORDER),
                   help="only use endpoints cleared for at least this data tier")
    p.add_argument("-d", "--directory", action="append", help="directory path or https:// URL (repeatable)")
    p.add_argument("--list", action="store_true", help="show which services resolve on this machine")
    args = p.parse_args()

    dap = LLMDAPClient(args.directory or [
        "~/.config/llmdap/directory.json",  # your personal overrides, if any
        str(HERE / "directory.json"),        # the shared directory
    ])

    for name in args.service or DEFAULT_ORDER:
        try:
            t = dap.lookup(name, required_classification=args.classification)
        except LLMDAPError as exc:
            print(f"  {name:<18} skipped: {exc}", file=sys.stderr)
            continue
        if local_endpoint_down(t):
            print(f"  {name:<18} skipped: nothing answering at {t.endpoint}", file=sys.stderr)
            continue
        if args.list:
            print(f"  {name:<18} ready: {t.model} ({t.dialect}, cleared for {t.classification})")
            continue
        print(f"→ {name}: {t.model} at {t.endpoint}", file=sys.stderr)
        try:
            print(chat(t, args.prompt))
            return 0
        except Exception as exc:
            print(f"  {name:<18} call failed: {exc}", file=sys.stderr)

    if args.list:
        return 0
    print("No service available. Set GITHUB_TOKEN or GEMINI_API_KEY, start Ollama, "
          "or relax -c.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
