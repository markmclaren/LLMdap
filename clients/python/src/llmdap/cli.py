import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional

from .client import CLASSIFICATION_ORDER, LLMDAPClient, LLMDAPError, file_uri_to_path

VALID_DIALECTS = {
    "openai-chat",
    "openai-responses",
    "anthropic-messages",
    "ollama",
    "google-genai",
    "bedrock-converse",
}

VALID_AUTH_METHODS = {
    "none",
    "env",
    "oidc-exchange",
    "secret-store",
    "portal-request",
}


def _default_directories() -> List[str]:
    env_dirs = os.getenv("LLMDAP_DIRECTORIES")
    if env_dirs:
        return [d.strip() for d in env_dirs.split(",") if d.strip()]
    local_path = Path.home() / ".config" / "llmdap" / "directory.json"
    return [local_path.as_uri()]


def _load_json_target(target: str) -> dict:
    if target.startswith(("http://", "https://")):
        with urllib.request.urlopen(target, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    if target.startswith("file://"):
        path = file_uri_to_path(target)
    else:
        path = Path(target).expanduser()
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_builtin(doc: dict) -> List[str]:
    errors: List[str] = []
    if not isinstance(doc, dict):
        return ["Root document must be a JSON object."]

    if doc.get("llmdap_version") != "0.1":
        errors.append(
            f"Unsupported or missing 'llmdap_version': expected '0.1', got {doc.get('llmdap_version')!r}."
        )

    records = doc.get("records")
    if not isinstance(records, dict) or not records:
        errors.append("'records' must be a non-empty JSON object mapping logical names to service records.")
        return errors

    for name, rec in records.items():
        if not isinstance(rec, dict):
            errors.append(f"[{name}] Record must be an object.")
            continue

        for req in ("endpoint", "dialect", "model", "auth"):
            if req not in rec:
                errors.append(f"[{name}] Missing required field '{req}'.")

        dialect = rec.get("dialect")
        if dialect and dialect not in VALID_DIALECTS:
            errors.append(f"[{name}] Invalid dialect '{dialect}'. Expected one of: {sorted(VALID_DIALECTS)}.")

        auth = rec.get("auth")
        if isinstance(auth, dict):
            method = auth.get("method")
            if method not in VALID_AUTH_METHODS:
                errors.append(
                    f"[{name}] Invalid auth.method '{method}'. Expected one of: {sorted(VALID_AUTH_METHODS)}."
                )
            if method == "oidc-exchange" and not auth.get("issuer"):
                errors.append(f"[{name}] auth.method 'oidc-exchange' requires 'issuer'.")
            if method in {"env", "secret-store", "portal-request"} and not auth.get("locator"):
                errors.append(f"[{name}] auth.method '{method}' requires 'locator'.")
        elif auth is not None:
            errors.append(f"[{name}] 'auth' must be an object.")

        gov = rec.get("governance")
        if isinstance(gov, dict) and "data_classification" in gov:
            dc = gov["data_classification"]
            if dc not in CLASSIFICATION_ORDER:
                errors.append(f"[{name}] Invalid governance.data_classification '{dc}'.")

    return errors


def cmd_lookup(args: argparse.Namespace) -> int:
    directories = args.directory if args.directory else _default_directories()
    client = LLMDAPClient(directory_urls=directories)

    try:
        resolved = client.lookup(
            args.name,
            required_classification=args.classification,
        )
    except LLMDAPError as exc:
        print(f"LLMDAP lookup failed: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        payload = {
            "id": resolved.id,
            "endpoint": resolved.endpoint,
            "dialect": resolved.dialect,
            "model": resolved.model,
            "authenticated": bool(resolved.api_key),
            "governance": resolved.governance,
            "capabilities": resolved.capabilities,
        }
        if args.show_secret:
            payload["api_key"] = resolved.api_key
            payload["headers"] = resolved.headers
        print(json.dumps(payload, indent=2))
    elif args.format == "env":
        print(f"export LLM_ENDPOINT={resolved.endpoint!r}")
        print(f"export LLM_MODEL={resolved.model!r}")
        print(f"export LLM_DIALECT={resolved.dialect!r}")
        if resolved.api_key and args.show_secret:
            print(f"export LLM_API_KEY={resolved.api_key!r}")
    else:
        print(f"Service:        {resolved.id}")
        print(f"Endpoint:       {resolved.endpoint}")
        print(f"Dialect:        {resolved.dialect}")
        print(f"Model:          {resolved.model}")
        print(f"Classification: {resolved.governance.get('data_classification', 'public')}")
        if resolved.api_key:
            secret_display = resolved.api_key if args.show_secret else "*** (pass --show-secret to reveal)"
            print(f"Credential:     {secret_display}")
        else:
            print("Credential:     None")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        doc = _load_json_target(args.target)
    except Exception as exc:
        print(f"Failed to load '{args.target}': {exc}", file=sys.stderr)
        return 1

    errors = _validate_builtin(doc)

    # Optionally validate against full JSON Schema if jsonschema is installed
    if args.schema:
        try:
            import jsonschema  # type: ignore

            schema_doc = _load_json_target(args.schema)
            validator = jsonschema.Draft202012Validator(schema_doc)
            for err in validator.iter_errors(doc):
                path = ".".join(str(p) for p in err.path) or "<root>"
                errors.append(f"[schema:{path}] {err.message}")
        except ImportError:
            print("Note: 'jsonschema' package not installed; ran built-in validator only.", file=sys.stderr)

    if errors:
        print(f"Validation FAILED for '{args.target}':", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    record_count = len(doc.get("records", {}))
    print(f"Valid LLMDAP v0.1 directory ({record_count} record(s)) in '{args.target}'.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmdap",
        description="Lightweight Language Model Directory Access Protocol (LLMDAP) CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Subcommand: lookup
    p_lookup = sub.add_parser("lookup", help="Resolve a logical model service name")
    p_lookup.add_argument("name", help="Logical service name (e.g., 'coding-large')")
    p_lookup.add_argument(
        "-d",
        "--directory",
        action="append",
        help="Directory URL or file:// URI (repeatable; overrides LLMDAP_DIRECTORIES)",
    )
    p_lookup.add_argument(
        "-c",
        "--classification",
        choices=list(CLASSIFICATION_ORDER.keys()),
        help="Minimum required data classification tier",
    )
    p_lookup.add_argument(
        "-f",
        "--format",
        choices=["text", "json", "env"],
        default="text",
        help="Output format (default: text)",
    )
    p_lookup.add_argument(
        "--show-secret",
        action="store_true",
        help="Include resolved credential in output",
    )
    p_lookup.set_defaults(func=cmd_lookup)

    # Subcommand: validate
    p_val = sub.add_parser("validate", help="Validate an LLMDAP directory JSON document")
    p_val.add_argument("target", help="Path or URL to directory JSON file")
    p_val.add_argument(
        "-s",
        "--schema",
        help="Optional path or URL to llmdap-directory.schema.json",
    )
    p_val.set_defaults(func=cmd_validate)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

