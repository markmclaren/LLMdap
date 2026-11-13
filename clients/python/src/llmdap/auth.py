import json
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, Tuple


class OIDCTokenBroker:
    """RFC 8693 OAuth 2.0 Token Exchange credential broker."""

    def __init__(self, subject_token_provider: Callable[[], str]):
        """
        subject_token_provider: Callable returning the local workload's base JWT
        (e.g., from K8s projected volume, Slurm job env, or user OIDC login cache).
        """
        self.subject_token_provider = subject_token_provider
        self._token_cache: Dict[str, Tuple[float, str]] = {}

    def resolve(self, auth_cfg: dict) -> str:
        cache_key = f"{auth_cfg.get('issuer')}|{auth_cfg.get('audience')}"
        now = time.time()

        # Return cached short-lived token if valid (with 30s safety buffer)
        if cache_key in self._token_cache:
            expires_at, token = self._token_cache[cache_key]
            if now < (expires_at - 30):
                return token

        # 1. Discover token_endpoint via standard OIDC .well-known metadata
        issuer = auth_cfg["issuer"].rstrip("/")
        well_known_url = f"{issuer}/.well-known/openid-configuration"
        with urllib.request.urlopen(well_known_url, timeout=5) as resp:
            oidc_meta = json.loads(resp.read().decode("utf-8"))
        token_endpoint = oidc_meta["token_endpoint"]

        # 2. Execute RFC 8693 Token Exchange
        subject_token = self.subject_token_provider()
        payload = urllib.parse.urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": subject_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
                "audience": auth_cfg["audience"],
                "scope": " ".join(auth_cfg.get("scopes", [])),
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            token_endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            token_resp = json.loads(resp.read().decode("utf-8"))

        access_token = token_resp["access_token"]
        expires_in = int(token_resp.get("expires_in", 900))
        self._token_cache[cache_key] = (now + expires_in, access_token)
        return access_token

