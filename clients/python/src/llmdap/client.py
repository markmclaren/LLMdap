"""LLMDAP reference client: look up a logical service name, get back how to call it."""
import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Sensitivity tiers, lowest to highest. A record cleared for a tier may carry any lower tier.
CLASSIFICATION_ORDER = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

DEFAULT_DIRECTORY = "~/.config/llmdap/directory.json"


class LLMDAPError(Exception):
    """Lookup failed: name not found, policy refused, or credential unavailable."""


@dataclass
class ResolvedModel:
    name: str
    endpoint: str
    dialect: str
    model: str
    classification: str
    api_key: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)


def file_uri_to_path(uri: str) -> Path:
    """file:// URI -> Path, accepting the file:///~/... shorthand for the home directory."""
    raw = urllib.request.url2pathname(uri[len("file://"):])
    if raw.startswith("/~"):
        raw = raw[1:]
    return Path(raw).expanduser()


def load_directory(url: str) -> dict:
    """Read a directory from https://, file://, or a plain file path."""
    if url.startswith("http://"):
        raise LLMDAPError("Remote directories must use https://")
    if not url.startswith("https://"):
        path = file_uri_to_path(url) if url.startswith("file://") else Path(url).expanduser()
        return json.loads(path.read_text(encoding="utf-8"))
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


class LLMDAPClient:
    def __init__(self, directory_urls: Optional[List[str]] = None):
        self.directory_urls = directory_urls or [DEFAULT_DIRECTORY]
        # auth.method -> function(auth_cfg) returning a credential (or None)
        self.auth_handlers: Dict[str, Callable[[dict], Optional[str]]] = {
            "none": lambda cfg: None,
            "env": _auth_env,
            "portal-request": _auth_portal,
        }

    def register_auth_handler(self, method: str, handler: Callable[[dict], Optional[str]]) -> None:
        """Plug in other credential sources (Vault, OIDC token exchange, ...)."""
        self.auth_handlers[method] = handler

    def find_record(self, name: str) -> dict:
        override = os.getenv("LLMDAP_OVERRIDE_" + name.upper().replace("-", "_"))
        if override:
            return json.loads(override)
        for url in self.directory_urls:
            try:
                records = load_directory(url).get("records", {})
            except FileNotFoundError:
                continue  # an optional local directory that doesn't exist
            except Exception as exc:
                raise LLMDAPError(f"Could not read directory {url}: {exc}") from exc
            if name in records:
                return records[name]
        raise LLMDAPError(f"Service '{name}' not found in {self.directory_urls}")

    def lookup(self, name: str, required_classification: Optional[str] = None) -> ResolvedModel:
        record = self.find_record(name)
        classification = record.get("classification", "public")

        # Policy is checked before any credential is fetched or connection made.
        if required_classification:
            # An unknown tier on the record counts as below everything, so it is refused.
            if CLASSIFICATION_ORDER.get(classification, -1) < CLASSIFICATION_ORDER[required_classification]:
                raise LLMDAPError(
                    f"'{name}' is only cleared for '{classification}' data, "
                    f"but '{required_classification}' was required."
                )

        auth = record["auth"]
        handler = self.auth_handlers.get(auth["method"])
        if not handler:
            raise LLMDAPError(f"No handler for auth method '{auth['method']}'")
        secret = handler(auth)

        headers = {}
        if secret:
            headers[auth.get("header", "Authorization")] = auth.get("prefix", "Bearer ") + secret

        return ResolvedModel(
            name=name,
            endpoint=record["endpoint"],
            dialect=record["dialect"],
            model=record["model"],
            classification=classification,
            api_key=secret,
            headers=headers,
        )


def _auth_env(auth: dict) -> str:
    value = os.getenv(auth["locator"])
    if not value:
        raise LLMDAPError(f"Set the environment variable {auth['locator']}")
    return value


def _auth_portal(auth: dict) -> str:
    raise LLMDAPError(f"You don't have access yet. Request it at: {auth['locator']}")
