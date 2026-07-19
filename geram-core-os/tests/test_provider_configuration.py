"""Focused tests for provider settings and the localhost config API."""

import asyncio
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.core.providers.base import ProviderCredential


with (
    patch.dict(os.environ, {}, clear=True),
    patch("dotenv.load_dotenv", return_value=False),
    patch("pathlib.Path.mkdir"),
):
    from app.api import config as config_api
    from app.core.config import Settings, SettingsValidationError
    from app.core.credential_pool import CredentialPoolManager


class ProviderSettingsTests(unittest.TestCase):
    def test_default_role_mappings(self):
        configuration = Settings({}, create_runtime_dirs=False)
        self.assertEqual(configuration.IRIS_PROVIDER, "gemini")
        self.assertEqual(configuration.ARES_PROVIDER, "openai")

    def test_provider_ids_normalize_to_lowercase(self):
        configuration = Settings(
            {"IRIS_PROVIDER": "GEMINI", "ARES_PROVIDER": "GroQ"},
            create_runtime_dirs=False,
        )
        self.assertEqual(configuration.IRIS_PROVIDER, "gemini")
        self.assertEqual(configuration.ARES_PROVIDER, "groq")

    def test_ollama_configuration_is_keyless_and_has_local_defaults(self):
        configuration = Settings(
            {
                "IRIS_PROVIDER": "OLLAMA",
                "IRIS_MODEL": "llama3.2:1b",
            },
            create_runtime_dirs=False,
        )
        self.assertEqual(configuration.IRIS_PROVIDER, "ollama")
        self.assertEqual(configuration.provider_api_key("ollama"), "")
        self.assertEqual(configuration.provider_timeout("ollama"), 120.0)

    def test_legacy_model_aliases_remain_effective(self):
        configuration = Settings(
            {
                "GEMINI_MODEL": "legacy-gemini-model",
                "CODEX_MODEL": "legacy-openai-model",
            },
            create_runtime_dirs=False,
        )
        self.assertEqual(configuration.IRIS_MODEL, "legacy-gemini-model")
        self.assertEqual(configuration.ARES_MODEL, "legacy-openai-model")
        self.assertEqual(configuration.GEMINI_MODEL, "legacy-gemini-model")
        self.assertEqual(configuration.CODEX_MODEL, "legacy-openai-model")

    def test_unsupported_provider_is_rejected(self):
        with self.assertRaises(SettingsValidationError) as raised:
            Settings(
                {"IRIS_PROVIDER": "unsupported"},
                create_runtime_dirs=False,
            )
        self.assertEqual(raised.exception.code, "unsupported_provider")

    def test_identical_primary_and_fallback_are_rejected(self):
        with self.assertRaises(SettingsValidationError) as raised:
            Settings(
                {
                    "IRIS_PROVIDER": "gemini",
                    "IRIS_FALLBACK_PROVIDER": "GEMINI",
                },
                create_runtime_dirs=False,
            )
        self.assertEqual(raised.exception.code, "identical_primary_fallback")

    def test_model_control_characters_and_timeout_range_are_rejected(self):
        with self.assertRaises(SettingsValidationError):
            Settings({"IRIS_MODEL": "invalid\nmodel"}, create_runtime_dirs=False)
        with self.assertRaises(SettingsValidationError):
            Settings(
                {"GEMINI_TIMEOUT_SECONDS": "301"},
                create_runtime_dirs=False,
            )

    def test_credential_store_must_remain_outside_source_tree(self):
        with self.assertRaises(SettingsValidationError) as raised:
            Settings(
                {"GERAM_LOCAL_DATA_DIR": str(config_api.ROOT_DIR / "static" / "data")},
                create_runtime_dirs=False,
            )
        self.assertEqual(raised.exception.code, "unsafe_local_data_dir")

    def test_provider_credential_masks_normal_rendering_and_serialization(self):
        test_value = "unit-test-provider-credential"
        credential = ProviderCredential(provider_id="gemini", secret=test_value)
        rendered = (
            repr(credential),
            str(credential),
            credential.model_dump_json(),
            str(credential.model_dump(mode="json")),
        )
        self.assertTrue(all(test_value not in value for value in rendered))
        with self.assertRaises(TypeError):
            pickle.dumps(credential)


class ProviderConfigApiTests(unittest.TestCase):
    def _run_update(self, env_path: Path, **fields):
        payload = config_api.ConfigKeysUpdate(**fields)
        with patch.object(config_api, "ENV_PATH", env_path):
            return asyncio.run(config_api.actualizar_keys(payload))

    def test_missing_key_is_rejected_when_selecting_remote_provider(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text("IRIS_PROVIDER=gemini\n")
            with self.assertRaises(HTTPException) as raised:
                self._run_update(env_path, IRIS_PROVIDER="groq")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["code"], "missing_provider_key")
        self.assertEqual(raised.exception.detail["field"], "GROQ_API_KEY")

    def test_provider_and_credential_are_saved_atomically(self):
        test_value = "unit-test-groq-credential"
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text("IRIS_PROVIDER=gemini\n")
            response = self._run_update(
                env_path,
                IRIS_PROVIDER="GROQ",
                GROQ_API_KEY=test_value,
            )
            saved = env_path.read_text()

        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            set(response["actualizados"]),
            {"IRIS_PROVIDER", "GROQ_API_KEY"},
        )
        self.assertIn("IRIS_PROVIDER=groq", saved)
        self.assertIn("GROQ_API_KEY=", saved)
        self.assertNotIn(test_value, str(response))

    def test_provider_selection_accepts_an_existing_pool_credential(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            env_path = root / ".env"
            env_path.write_text("IRIS_PROVIDER=gemini\n")
            pool = CredentialPoolManager(root / "pool" / "credentials.sqlite3")
            pool.add_credential(
                "groq",
                "unit-test project",
                "unit-test-groq-pool-secret",
            )
            with patch.object(config_api, "credential_pool_manager", pool):
                response = self._run_update(env_path, IRIS_PROVIDER="groq")

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["actualizados"], ["IRIS_PROVIDER"])

    def test_ollama_selection_does_not_require_an_api_key(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text("IRIS_PROVIDER=gemini\n")
            response = self._run_update(
                env_path,
                IRIS_PROVIDER="ollama",
                IRIS_MODEL="llama3.2:1b",
            )
            saved = env_path.read_text()

        self.assertEqual(response["status"], "ok")
        self.assertIn("IRIS_PROVIDER=ollama", saved)
        self.assertNotIn("OLLAMA_API_KEY", saved)

    def test_unchanged_masked_credential_is_not_written(self):
        test_value = "unit-test-openai-credential"
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            original = f"OPENAI_API_KEY={test_value}\n"
            env_path.write_text(original)
            masked = config_api._enmascarar(test_value)
            response = self._run_update(env_path, OPENAI_API_KEY=masked)
            saved = env_path.read_text()

        self.assertEqual(response["status"], "sin_cambios")
        self.assertEqual(saved, original)

    def test_credentials_are_never_returned_by_get_or_post(self):
        test_value = "unit-test-gemini-credential"
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text(f"GEMINI_API_KEY={test_value}\n")
            with patch.object(config_api, "ENV_PATH", env_path):
                get_response = asyncio.run(config_api.obtener_keys())
                post_response = asyncio.run(
                    config_api.actualizar_keys(
                        config_api.ConfigKeysUpdate(IRIS_MODEL="custom-model")
                    )
                )

        self.assertNotIn(test_value, get_response.values())
        self.assertNotIn(test_value, str(post_response))
        self.assertTrue(get_response["GEMINI_API_KEY"].startswith("*"))

    def test_unrelated_save_does_not_require_inherited_openai_key(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text("ARES_PROVIDER=openai\n")
            response = self._run_update(
                env_path,
                NOTION_DATABASE_ID="unit-test-database-id",
            )
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["actualizados"], ["NOTION_DATABASE_ID"])

    def test_extended_integration_credentials_are_masked_and_saved(self):
        test_value = "unit-test-calendar-credentials.json"
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text("IRIS_PROVIDER=gemini\n")
            response = self._run_update(
                env_path,
                GOOGLE_CALENDAR_CREDENTIALS_PATH=test_value,
                GOOGLE_CALENDAR_ID="primary",
                SPOTIFY_ACCESS_TOKEN="unit-test-spotify-token",
                OBSIDIAN_VAULT_PATH="/unit-test/vault",
            )
            with patch.object(config_api, "ENV_PATH", env_path):
                returned = asyncio.run(config_api.obtener_keys())

        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            set(response["actualizados"]),
            {
                "GOOGLE_CALENDAR_CREDENTIALS_PATH",
                "GOOGLE_CALENDAR_ID",
                "SPOTIFY_ACCESS_TOKEN",
                "OBSIDIAN_VAULT_PATH",
            },
        )
        self.assertNotEqual(returned["GOOGLE_CALENDAR_CREDENTIALS_PATH"], test_value)
        self.assertTrue(returned["SPOTIFY_ACCESS_TOKEN"].startswith("*"))

    def test_provider_catalog_contains_only_public_fields(self):
        catalog = asyncio.run(config_api.obtener_proveedores())
        allowed_fields = {
            "provider_id",
            "display_label",
            "default_model",
            "requires_api_key",
            "implementation_available",
            "input_modalities",
        }
        self.assertEqual(
            {item["provider_id"] for item in catalog},
            {
                "openai", "gemini", "groq", "ollama", "anthropic",
                "mistral", "deepseek", "xai", "perplexity", "together",
                "openrouter", "cerebras", "fireworks", "moonshot",
            },
        )
        self.assertTrue(all(set(item) == allowed_fields for item in catalog))
        ollama = next(item for item in catalog if item["provider_id"] == "ollama")
        self.assertFalse(ollama["requires_api_key"])
        self.assertTrue(ollama["implementation_available"])
        gemini = next(item for item in catalog if item["provider_id"] == "gemini")
        self.assertEqual(gemini["input_modalities"], ["text", "image", "audio"])


if __name__ == "__main__":
    unittest.main()
