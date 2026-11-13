import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llmdap import LLMDAPClient, LLMDAPError
from llmdap.cli import main as cli_main


class TestLLMDAPClient(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.tmpdir.name)

        self.local_dir_file = self.base_path / "local.json"
        self.org_dir_file = self.base_path / "org.json"

        self.local_dir_file.write_text(
            json.dumps(
                {
                    "llmdap_version": "0.1",
                    "directory": "local-workstation",
                    "records": {
                        "coding-fast": {
                            "endpoint": "http://localhost:11434/v1",
                            "dialect": "ollama",
                            "model": "qwen3-coder:7b",
                            "auth": {"method": "none"},
                            "governance": {"data_classification": "restricted"},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        self.org_dir_file.write_text(
            json.dumps(
                {
                    "llmdap_version": "0.1",
                    "directory": "example.org",
                    "records": {
                        "coding-fast": {
                            "endpoint": "https://api.openai.com/v1",
                            "dialect": "openai-chat",
                            "model": "gpt-4.1-mini",
                            "auth": {"method": "env", "locator": "TEST_OPENAI_KEY"},
                            "governance": {"data_classification": "public"},
                        },
                        "frontier-reasoning": {
                            "endpoint": "https://api.anthropic.com/v1",
                            "dialect": "anthropic-messages",
                            "model": "claude-sonnet-4-6",
                            "auth": {
                                "method": "env",
                                "locator": "TEST_ANTHROPIC_KEY",
                                "header": "x-api-key",
                                "prefix": "",
                            },
                            "governance": {"data_classification": "internal"},
                        },
                        "unprovisioned-service": {
                            "endpoint": "https://api.vendor.example/v1",
                            "dialect": "openai-chat",
                            "model": "vendor-pro",
                            "auth": {
                                "method": "portal-request",
                                "locator": "https://portal.example.org/ai/request",
                            },
                            "governance": {"data_classification": "internal"},
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

        self.client = LLMDAPClient(
            [
                self.local_dir_file.as_uri(),
                self.org_dir_file.as_uri(),
            ]
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_hierarchical_resolution_prefers_first_directory(self):
        resolved = self.client.lookup("coding-fast")
        self.assertEqual(resolved.endpoint, "http://localhost:11434/v1")
        self.assertEqual(resolved.dialect, "ollama")
        self.assertIsNone(resolved.api_key)

    @patch.dict(os.environ, {"TEST_ANTHROPIC_KEY": "sk-ant-test-123"})
    def test_fallback_to_org_directory_and_custom_header(self):
        resolved = self.client.lookup("frontier-reasoning")
        self.assertEqual(resolved.endpoint, "https://api.anthropic.com/v1")
        self.assertEqual(resolved.api_key, "sk-ant-test-123")
        self.assertEqual(resolved.headers, {"x-api-key": "sk-ant-test-123"})

    @patch.dict(os.environ, {"TEST_ANTHROPIC_KEY": "sk-ant-test-123"})
    def test_governance_enforcement_blocks_insufficient_tier(self):
        # 'frontier-reasoning' is 'internal'; requesting 'restricted' must fail
        with self.assertRaises(LLMDAPError) as ctx:
            self.client.lookup("frontier-reasoning", required_classification="restricted")
        self.assertIn("Governance policy violation", str(ctx.exception))

        # Requesting 'public' on an 'internal' endpoint succeeds (internal >= public)
        resolved = self.client.lookup("frontier-reasoning", required_classification="public")
        self.assertEqual(resolved.model, "claude-sonnet-4-6")

    def test_portal_request_raises_onboarding_url(self):
        with self.assertRaises(LLMDAPError) as ctx:
            self.client.lookup("unprovisioned-service")
        self.assertIn("https://portal.example.org/ai/request", str(ctx.exception))

    def test_custom_auth_handler_registration(self):
        self.org_dir_file.write_text(
            json.dumps(
                {
                    "llmdap_version": "0.1",
                    "records": {
                        "vault-model": {
                            "endpoint": "https://inference.internal/v1",
                            "dialect": "openai-chat",
                            "model": "llama-3.3-70b",
                            "auth": {
                                "method": "secret-store",
                                "locator": "vault://ai/prod/llama",
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        fresh_client = LLMDAPClient([self.org_dir_file.as_uri()])
        fresh_client.register_auth_handler(
            "secret-store",
            lambda cfg: f"minted-token-for-{cfg['locator']}",
        )
        resolved = fresh_client.lookup("vault-model")
        self.assertEqual(
            resolved.headers["Authorization"],
            "Bearer minted-token-for-vault://ai/prod/llama",
        )

    @patch.dict(
        os.environ,
        {
            "LLMDAP_OVERRIDE_CODING_FAST": json.dumps(
                {
                    "endpoint": "http://10.0.0.99:8000/v1",
                    "dialect": "openai-chat",
                    "model": "override-model",
                    "auth": {"method": "none"},
                }
            )
        },
    )
    def test_process_env_override_takes_precedence(self):
        resolved = self.client.lookup("coding-fast")
        self.assertEqual(resolved.endpoint, "http://10.0.0.99:8000/v1")
        self.assertEqual(resolved.model, "override-model")

    def test_cli_validate_and_lookup(self):
        with self.assertRaises(SystemExit) as cm:
            cli_main(["validate", str(self.org_dir_file)])
        self.assertEqual(cm.exception.code, 0)

        with self.assertRaises(SystemExit) as cm:
            cli_main(
                [
                    "lookup",
                    "coding-fast",
                    "-d",
                    self.local_dir_file.as_uri(),
                    "-c",
                    "restricted",
                    "-f",
                    "json",
                ]
            )
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()

