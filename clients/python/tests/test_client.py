import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llmdap import LLMDAPClient, LLMDAPError
from llmdap.cli import main as cli_main

REPO = Path(__file__).resolve().parents[3]


def write_directory(path: Path, records: dict) -> str:
    path.write_text(json.dumps({"llmdap_version": "0.1", "records": records}), encoding="utf-8")
    return path.as_uri()


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.local = write_directory(base / "local.json", {
            "coding": {"endpoint": "http://localhost:11434", "dialect": "ollama", "model": "qwen3:8b",
                       "auth": {"method": "none"}, "classification": "restricted"},
        })
        self.org = write_directory(base / "org.json", {
            "coding": {"endpoint": "https://api.openai.com/v1", "dialect": "openai-chat", "model": "gpt-4.1-mini",
                       "auth": {"method": "env", "locator": "TEST_OPENAI_KEY"}},
            "reasoning": {"endpoint": "https://api.anthropic.com/v1", "dialect": "anthropic-messages",
                          "model": "claude-sonnet-4-6", "classification": "internal",
                          "auth": {"method": "env", "locator": "TEST_ANTHROPIC_KEY",
                                   "header": "x-api-key", "prefix": ""}},
            "premium": {"endpoint": "https://api.vendor.example/v1", "dialect": "openai-chat", "model": "pro",
                        "auth": {"method": "portal-request", "locator": "https://portal.example.org/ai"}},
        })
        self.missing = (base / "does-not-exist.json").as_uri()
        self.client = LLMDAPClient([self.missing, self.local, self.org])

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_directory_wins_and_missing_files_are_skipped(self):
        r = self.client.lookup("coding")
        self.assertEqual((r.dialect, r.classification, r.api_key), ("ollama", "restricted", None))

    @patch.dict(os.environ, {"TEST_ANTHROPIC_KEY": "sk-ant-test"})
    def test_env_credential_with_custom_header(self):
        r = self.client.lookup("reasoning")
        self.assertEqual(r.headers, {"x-api-key": "sk-ant-test"})

    def test_missing_env_var_is_reported(self):
        with self.assertRaisesRegex(LLMDAPError, "TEST_OPENAI_KEY"):
            LLMDAPClient([self.org]).lookup("coding")

    def test_classification_is_checked_before_credentials(self):
        # 'reasoning' is internal; its env var is unset, so reaching auth would raise a different error.
        with self.assertRaisesRegex(LLMDAPError, "only cleared for 'internal'"):
            self.client.lookup("reasoning", required_classification="restricted")

    def test_unclassified_record_defaults_to_public(self):
        with self.assertRaisesRegex(LLMDAPError, "only cleared for 'public'"):
            LLMDAPClient([self.org]).lookup("coding", required_classification="internal")

    def test_portal_request_points_to_onboarding(self):
        with self.assertRaisesRegex(LLMDAPError, "https://portal.example.org/ai"):
            self.client.lookup("premium")

    def test_not_found(self):
        with self.assertRaisesRegex(LLMDAPError, "not found"):
            self.client.lookup("nope")

    def test_custom_auth_handler(self):
        uri = write_directory(Path(self.tmp.name) / "vault.json", {
            "vaulted": {"endpoint": "https://inference.internal/v1", "dialect": "openai-chat", "model": "m",
                        "auth": {"method": "secret-store", "locator": "vault://ai/llama"}},
        })
        client = LLMDAPClient([uri])
        client.register_auth_handler("secret-store", lambda cfg: "token-for-" + cfg["locator"])
        self.assertEqual(client.lookup("vaulted").headers["Authorization"], "Bearer token-for-vault://ai/llama")

    @patch.dict(os.environ, {"LLMDAP_OVERRIDE_CODING": json.dumps(
        {"endpoint": "http://10.0.0.9:8000/v1", "dialect": "openai-chat", "model": "override",
         "auth": {"method": "none"}})})
    def test_env_override_takes_precedence(self):
        self.assertEqual(self.client.lookup("coding").model, "override")

    def test_home_shorthand_in_file_uri(self):
        from llmdap.client import file_uri_to_path
        self.assertEqual(file_uri_to_path("file:///~/x.json"), Path.home() / "x.json")

    def test_plain_paths_work(self):
        path = self.local[len("file://"):]
        self.assertEqual(LLMDAPClient([path]).lookup("coding").dialect, "ollama")

    def test_plain_http_directories_are_refused(self):
        with self.assertRaisesRegex(LLMDAPError, "https"):
            LLMDAPClient(["http://example.org/llmdap.json"]).lookup("coding")

    def test_cli_lookup(self):
        with self.assertRaises(SystemExit) as cm:
            cli_main(["lookup", "coding", "-d", self.local, "-c", "restricted", "--json"])
        self.assertEqual(cm.exception.code, 0)


class TestExampleDirectory(unittest.TestCase):
    def test_example_matches_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("pip install jsonschema to run")
        schema = json.loads((REPO / "schema" / "llmdap-directory.schema.json").read_text())
        doc = json.loads((REPO / "examples" / "directory.json").read_text())
        jsonschema.Draft202012Validator(schema).validate(doc)


if __name__ == "__main__":
    unittest.main()
