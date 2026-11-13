#!/usr/bin/env python3
"""LLMDAP free-tier demo: resolve a logical service name, then call it directly.

Zero dependencies (stdlib only). Run from anywhere in the repo checkout:

    python examples/free-tier/demo.py "Explain LDAP in one sentence"
    python examples/free-tier/demo.py --service chat-gemini "Hello"
    python examples/free-tier/demo.py --classification restricted "Sensitive prompt"
    python examples/free-tier/demo.py --list

With no --service, it walks a preference list and uses the first record whose
credentials resolve and whose endpoint answers — the application never names a
vendor or model itself.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "clients" / "python" / "src"))  # use repo client without pip install

from llmdap import LLMDAPClient, LLMDAPError, ResolvedModel  # noqa: E402

DEFAULT_PREFERENCE = ["chat-local", "chat-dmr", "chat-github", "chat-gemini", "chat-groq", "reasoning-premium"]


def _post(url: str, body: dict, headers: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def chat(target: ResolvedModel, prompt: str) -> str:
    """Dispatch on the record's dialect. Inference goes straight to the host (no proxy)."""
    base = target.endpoint.rstrip("/")
    messages = [{"role": "user", "content": prompt}]

    if target.dialect == "openai-chat":
        data = _post(f"{base}/chat/completions", {"model": target.model, "messages": messages}, target.headers)
        return data["choices"][0]["message"]["content"]

    if target.dialect == "ollama":
        data = _post(f"{base}/api/chat", {"model": target.model, "messages": messages, "stream": False}, target.headers)
        return data["message"]["content"]

    if target.dialect == "anthropic-messages":
        headers = {"anthropic-version": "2023-06-01", **target.headers}
        data = _post(f"{base}/messages", {"model": target.model, "max_tokens": 1024, "messages": messages}, headers)
        return "".join(b.get("text", "") for b in data["content"])

    raise RuntimeError(f"demo.py has no adapter for dialect '{target.dialect}'")


def reachable(target: ResolvedModel) -> bool:
    """Cheap pre-flight for local endpoints so auto-selection skips stopped runtimes quickly."""
    base = target.endpoint.rstrip("/")
    if target.dialect == "ollama":
        probe = f"{base}/api/tags"
    elif target.endpoint.startswith("http://"):
        probe = f"{base}/models"
    else:
        return True
    try:
        urllib.request.urlopen(probe, timeout=2).close()
        return True
    except Exception:
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("prompt", nargs="?", default="In one sentence, what problem does LDAP solve?")
    p.add_argument("-s", "--service", action="append", help="Logical service name (repeatable = preference order)")
    p.add_argument("-c", "--classification", choices=["public", "internal", "confidential", "restricted"],
                   help="Minimum data classification the endpoint must be cleared for")
    p.add_argument("-d", "--directory", action="append",
                   help="Directory URL or file:// URI (repeatable, searched in order). "
                        "Default: ~/.config/llmdap/directory.json then this folder's directory.json")
    p.add_argument("--list", action="store_true", help="Show each record and whether it resolves here")
    args = p.parse_args()

    directories = args.directory or [
        "file:///~/.config/llmdap/directory.json",  # personal overrides (optional)
        (HERE / "directory.json").as_uri(),          # the shared "organisational" directory
    ]
    dap = LLMDAPClient(directories)
    services = args.service or DEFAULT_PREFERENCE

    if args.list:
        for name in services:
            try:
                t = dap.lookup(name, required_classification=args.classification)
                status = "ready" if reachable(t) else "unreachable"
                print(f"  {name:<18} {status:<12} {t.dialect:<19} {t.model}")
            except LLMDAPError as exc:
                print(f"  {name:<18} {'skipped':<12} {exc}")
        return 0

    for name in services:
        try:
            target = dap.lookup(name, required_classification=args.classification)
        except LLMDAPError as exc:
            print(f"· {name}: {exc}", file=sys.stderr)
            continue
        if not reachable(target):
            print(f"· {name}: endpoint {target.endpoint} not answering", file=sys.stderr)
            continue

        print(f"→ {name} resolved to {target.model} via {target.endpoint} "
              f"[{target.dialect}, cleared for '{target.governance.get('data_classification', 'public')}']",
              file=sys.stderr)
        try:
            print(chat(target, args.prompt))
            return 0
        except Exception as exc:
            print(f"· {name}: call failed: {exc}", file=sys.stderr)

    print("No service could satisfy the request. Set one of GITHUB_TOKEN / GEMINI_API_KEY / GROQ_API_KEY, "
          "start Ollama, or relax --classification.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
