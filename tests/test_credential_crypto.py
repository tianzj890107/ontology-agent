import base64
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "open-claude"))

from open_claude import credential_crypto


class CredentialCryptoStartupTests(unittest.TestCase):
    def test_missing_secret_is_explicit_degraded_status(self):
        with patch.object(credential_crypto, "_configured_secret_values", return_value=[]):
            status = credential_crypto.startup_crypto_check()
        self.assertEqual(status["mode"], "degraded")
        self.assertFalse(status["configured"])


@unittest.skipUnless(credential_crypto.AESGCM is not None, "cryptography is required")
class CredentialCryptoTests(unittest.TestCase):
    def setUp(self):
        self.key = bytes(range(32))
        self.secret = base64.b64encode(self.key).decode("ascii")
        self.iv = bytes(range(12))
        self.ciphertext = base64.b64encode(
            self.iv + credential_crypto.AESGCM(self.key).encrypt(
                self.iv, b"correct-password", None
            )
        ).decode("ascii")

    def test_encrypted_password_with_correct_secret_decrypts(self):
        with patch.dict(os.environ, {"ONTOLOGY_CRYPTO_SECRET": self.secret}, clear=False):
            self.assertEqual(
                credential_crypto.decrypt_connection_credential(self.ciphertext),
                "correct-password",
            )

    def test_encrypted_password_without_secret_fails_closed(self):
        with patch.dict(os.environ, {}, clear=False):
            for name in credential_crypto.CRYPTO_SECRET_ENV_NAMES:
                os.environ.pop(name, None)
            with self.assertRaises(credential_crypto.CredentialDecryptionError) as caught:
                credential_crypto.decrypt_connection_credential(self.ciphertext)
        self.assertEqual(caught.exception.code, "DATABASE_CREDENTIAL_DECRYPTION_FAILED")
        self.assertNotIn(self.ciphertext, str(caught.exception))

    def test_encrypted_password_with_wrong_secret_fails_closed(self):
        wrong = base64.b64encode(bytes(reversed(range(32)))).decode("ascii")
        with patch.dict(os.environ, {"ONTOLOGY_CRYPTO_SECRET": wrong}, clear=False):
            with self.assertRaises(credential_crypto.CredentialDecryptionError) as caught:
                credential_crypto.decrypt_connection_credential(self.ciphertext)
        self.assertEqual(caught.exception.code, "DATABASE_CREDENTIAL_DECRYPTION_FAILED")

    def test_plaintext_credential_uses_legacy_explicit_path(self):
        self.assertEqual(
            credential_crypto.decrypt_connection_credential(
                "plain-password", explicitly_encrypted=False
            ),
            "plain-password",
        )


def _load_server_without_model_dependencies():
    names = ("open_claude.repl", "open_claude.profile", "open_claude.api", "open_claude.config")
    originals = {name: sys.modules.get(name) for name in names}
    import open_claude.config as real_config

    repl = types.ModuleType("open_claude.repl")
    repl.Conversation = object
    profile = types.ModuleType("open_claude.profile")
    profile.AgentProfile = object
    api = types.ModuleType("open_claude.api")
    api.stream_message = lambda *args, **kwargs: iter(())
    config = types.ModuleType("open_claude.config")
    config.AVAILABLE_MODELS = []
    config.PROVIDERS = {}
    config.get_api_key_for = lambda provider: None
    config.get_config_path = lambda: Path("/tmp/no-config")
    config.get_max_tokens = lambda: 1
    config.get_model = lambda: "test"
    config.get_model_provider = lambda model: "test"
    config.load_config = lambda: {}
    config.resolve_model = lambda model: model
    config.validate_inference_params = real_config.validate_inference_params
    config.configured_models = lambda: []
    for name, module in zip(names, (repl, profile, api, config)):
        sys.modules[name] = module
    try:
        spec = importlib.util.spec_from_file_location(
            "credential_server_test", ROOT / "open-claude" / "oc_codex_server.py"
        )
        server = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(server)
        return server
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


@unittest.skipUnless(credential_crypto.AESGCM is not None, "cryptography is required")
class MissionDatabaseConfigTests(unittest.TestCase):
    def test_missing_secret_does_not_materialize_or_write_ciphertext_config(self):
        key = bytes(range(32))
        iv = bytes(range(12))
        ciphertext = base64.b64encode(
            iv + credential_crypto.AESGCM(key).encrypt(iv, b"db-password", None)
        ).decode("ascii")
        server = _load_server_without_model_dependencies()
        with patch.object(credential_crypto, "_configured_secret_values", return_value=[]), tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(credential_crypto.CredentialDecryptionError) as caught:
                server.write_mission_database_config(
                    {"dataSource": {"host": "db", "database": "ontology",
                                     "username": "agent", "password": ciphertext}},
                    tmp,
                )
            self.assertEqual(caught.exception.code, "DATABASE_CREDENTIAL_DECRYPTION_FAILED")
            self.assertFalse((Path(tmp) / "input" / ".db_connection.json").exists())

    def test_task_file_keeps_ciphertext_and_helper_decrypts_in_memory(self):
        key = bytes(range(32))
        secret = base64.b64encode(key).decode("ascii")
        iv = bytes(range(12))
        ciphertext = base64.b64encode(
            iv + credential_crypto.AESGCM(key).encrypt(iv, b"db-password", None)
        ).decode("ascii")
        server = _load_server_without_model_dependencies()
        with patch.dict(os.environ, {"ONTOLOGY_CRYPTO_SECRET": secret}, clear=False), tempfile.TemporaryDirectory() as tmp:
            path = server.write_mission_database_config(
                {"dataSource": {"host": "db", "database": "ontology",
                                 "username": "agent", "password": ciphertext,
                                 "sourceSchema": "ontology_dev"}},
                tmp,
            )
            self.assertEqual(path, "input/.db_connection.json")
            saved = json.loads((Path(tmp) / path).read_text(encoding="utf-8"))
            self.assertEqual(saved["password"], ciphertext)
            self.assertNotIn("db-password", (Path(tmp) / path).read_text(encoding="utf-8"))
            helper = (Path(tmp) / "input" / "db_connection.py")
            server.ensure_database_helpers(tmp, path)
            helper_text = helper.read_text(encoding="utf-8")
            self.assertIn("decrypt_connection_credential", helper_text)
            self.assertIn("source_schema", helper_text)
            self.assertIn("search_path", helper_text)
            self.assertIn("default_transaction_read_only", helper_text)


if __name__ == "__main__":
    unittest.main()
