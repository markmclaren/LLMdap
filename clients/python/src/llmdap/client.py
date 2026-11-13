import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

CLASSIFICATION_ORDER = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


class LLMDAPError(Exception):
    """Raised when an LLMDAP lookup, governance policy, or credential exchange fails."""


@dataclass
class ResolvedModel:
    id: str
    endpoint: str
    dialect: str
    model: str
    api_key: Optional[str]
    headers: Dict[str, str]
    governance: Dict[str, Any]
    capabilities: Dict[str, Any]


class LLMDAPClient:
    def __init__(self, directory_urls: Optional[List[str]] = None):
        if directory_urls is None:
            default_local = Path.home() / ".config" / "llmdap" / "directory.json"
            directory_urls = [default_local.as_uri()]
        self.directory_urls = directory_urls
        self._dir_cache: Dict[str, tuple[float, dict]] = {}
        self._auth_handlers: Dict[str, Callable[[dict], Optional[str]]] = {
            "none": lambda cfg: None,
            "env": self._resolve_env,
            "portal-request": self._resolve_portal,
        }

    def register_auth_handler(self, method: str, handler: Callable[[dict], Optional[str]]) -> None:
        self._auth_handlers[method] = handler

    def _fetch_directory(self, url: str) -> dict:
        now = time.time()
        if url in self._dir_cache:
            expires_at, data = self._dir_cache[url]
            if now < expires_at:
                return data

        if url.startswith("file://"):
            path = Path(urllib.request.url2pathname(url[7:])).expanduser()
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

        self._dir_cache[url] = (now + 300, data)
        return data

    def _resolve_env(self, auth_cfg: dict) -> str:
        var_name = auth_cfg.get("locator", "")
        val = os.getenv(var_name)
        if not val:
            raise LLMDAPError(f"Missing required environment variable: {var_name}")
        return val

    def _resolve_portal(self, auth_cfg: dict) -> str:
        raise LLMDAPError(
            f"Access not provisioned locally. Request an API key at: {auth_cfg.get('locator')}"
        )

    def _check_governance(self, logical_name: str, gov: dict, required_classification: Optional[str]) -> None:
        if not required_classification:
            return
        if required_classification not in CLASSIFICATION_ORDER:
            raise LLMDAPError(f"Unknown required_classification: '{required_classification}'")

        actual = gov.get("data_classification", "public")
        if actual not in CLASSIFICATION_ORDER:
            raise LLMDAPError(f"Record '{logical_name}' declares unknown classification: '{actual}'")

        if CLASSIFICATION_ORDER[actual] < CLASSIFICATION_ORDER[required_classification]:
            raise LLMDAPError(
                f"Governance policy violation for '{logical_name}': "
                f"requires '{required_classification}', endpoint is only cleared for '{actual}'."
            )

    def lookup(self, logical_name: str, required_classification: Optional[str] = None) -> ResolvedModel:
        record = None

        # 1. Check process environment override (JSON string)
        env_override = os.getenv(f"LLMDAP_OVERRIDE_{logical_name.upper().replace('-', '_')}")
        if env_override:
            record = json.loads(env_override)
        else:
            # 2. Walk directory chain in order
            for url in self.directory_urls:
                try:
                    directory = self._fetch_directory(url)
                    records = directory.get("records", {})
                    if logical_name in records:
                        record = records[logical_name]
                        break
                except FileNotFoundError:
                    continue
                except Exception:
                    continue

        if not record:
            raise LLMDAPError(f"Logical service '{logical_name}' not found in configured directories.")

        gov = record.get("governance", {})
        self._check_governance(logical_name, gov, required_classification)

        auth_cfg = record["auth"]
        method = auth_cfg["method"]
        if method not in self._auth_handlers:
            raise LLMDAPError(f"Unsupported auth method '{method}'. Register a handler first.")

        secret = self._auth_handlers[method](auth_cfg)
        headers: Dict[str, str] = {}
        if secret:
            header_name = auth_cfg.get("header", "Authorization")
            prefix = auth_cfg.get("prefix", "Bearer ")
            headers[header_name] = f"{prefix}{secret}"

        return ResolvedModel(
            id=logical_name,
            endpoint=record["endpoint"],
            dialect=record["dialect"],
            model=record["model"],
            api_key=secret,
            headers=headers,
            governance=gov,
            capabilities=record.get("capabilities", {}),
        )

