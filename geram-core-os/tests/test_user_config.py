"""Tests for the v3 (Paso 2) local user configuration: read/write, default
generation, 0600 permissions, blocked-path privacy controls, the /api/config
endpoints, and the global system-prompt injection into IRIS and A.R.E.S."""

import asyncio
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.api import orchestrator as orchestrator_api
from app.api import user_config as user_config_api
from app.api.ares_edits import _context_prompt
from app.core import user_config as uc
from app.core.workspace import WorkspaceError, WorkspaceService


class UserConfigCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / ".geram-config.json"

    def test_defaults_generated_and_written_with_0600(self):
        self.assertFalse(self.path.exists())
        config = uc.load_config(self.path, create_if_missing=True)
        self.assertTrue(self.path.exists())
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        # Estructura modular con los tres bloques documentados.
        self.assertEqual(config.ui_theme.core_identity_view, "core")
        self.assertEqual(config.privacy_controls.blocked_paths, [".env", "/etc/passwd"])
        self.assertFalse(config.user_profile.use_tts_notifications)
        self.assertEqual(config.onboarding.manual_version_seen, 0)

    def test_missing_file_without_create_does_not_write(self):
        config = uc.load_config(self.path, create_if_missing=False)
        self.assertFalse(self.path.exists())
        self.assertEqual(config, uc.default_config())

    def test_roundtrip_preserves_values(self):
        config = uc.default_config()
        config.user_profile.name = "Mauri"
        config.user_profile.age = 17
        config.user_profile.system_prompt_override = "Soy dev, llámame joven Mauri"
        config.user_profile.use_tts_notifications = True
        config.ui_theme.primary_color = "#00ffcc"
        config.ui_theme.core_identity_view = "pet"
        config.privacy_controls.blocked_paths = [".env", "secrets/prod.key"]
        uc.save_config(config, self.path)

        reloaded = uc.load_config(self.path)
        self.assertEqual(reloaded, config)

    def test_save_forces_0600_even_over_loose_preexisting_file(self):
        self.path.write_text("{}", encoding="utf-8")
        self.path.chmod(0o644)
        uc.save_config(uc.default_config(), self.path)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_invalid_identity_view_is_rejected(self):
        with self.assertRaises(ValidationError):
            uc.UiTheme(core_identity_view="hologram")

    def test_non_hex_color_is_rejected(self):
        # Evita inyección de CSS arbitrario en la variable --principal.
        with self.assertRaises(ValidationError):
            uc.UiTheme(primary_color="red; } body { display:none }")

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(ValidationError):
            uc.GeramConfig.model_validate({"user_profile": {"nickname": "x"}})

    def test_corrupt_file_raises_but_safe_loader_returns_defaults(self):
        self.path.write_text("{ this is not json", encoding="utf-8")
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            uc.load_config(self.path)
        self.assertEqual(uc.load_config_safe(self.path), uc.default_config())


class BlockedPathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / ".geram-config.json"

    def _with_blocked(self, entries):
        config = uc.default_config()
        config.privacy_controls.blocked_paths = entries
        uc.save_config(config, self.path)

    def test_blocks_by_basename_anywhere(self):
        self._with_blocked([".env"])
        self.assertTrue(uc.is_path_blocked("app/api/.env", ".env", self.path))
        self.assertTrue(uc.is_path_blocked(".env", ".env", self.path))

    def test_blocks_by_trailing_relative_segment(self):
        self._with_blocked(["secrets/prod.key"])
        self.assertTrue(uc.is_path_blocked("app/secrets/prod.key", "prod.key", self.path))

    def test_blocks_absolute_style_entry(self):
        self._with_blocked(["/etc/passwd"])
        self.assertTrue(uc.is_path_blocked("etc/passwd", "passwd", self.path))

    def test_does_not_block_unrelated_paths(self):
        self._with_blocked([".env", "secrets/prod.key"])
        self.assertFalse(uc.is_path_blocked("app/main.py", "main.py", self.path))
        self.assertFalse(uc.is_path_blocked("prod.key", "prod.key", self.path))

    def test_empty_blocklist_blocks_nothing(self):
        self._with_blocked([])
        self.assertFalse(uc.is_path_blocked("anything/.env", ".env", self.path))

    def test_workspace_read_file_enforces_blocked_paths(self):
        root = Path(self.temporary.name) / "workspace"
        root.mkdir()
        secret = root / "secret_data.py"
        secret.write_text("TOKEN = 'top secret'", encoding="utf-8")
        secret.chmod(0o644)
        service = WorkspaceService(root)
        # Sanity: sin bloqueo, se lee bien.
        with patch("app.core.workspace.is_path_blocked", return_value=False):
            self.assertEqual(service.read_file("secret_data.py")["content"], "TOKEN = 'top secret'")
        # Con bloqueo activo, read_file lo rechaza con protected_path.
        with patch("app.core.workspace.is_path_blocked", return_value=True):
            with self.assertRaises(WorkspaceError) as raised:
                service.read_file("secret_data.py")
            self.assertEqual(raised.exception.code, "protected_path")


class SystemPromptOverrideTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / ".geram-config.json"

    def test_reads_override_value(self):
        config = uc.default_config()
        config.user_profile.system_prompt_override = "  Soy joven Mauri  "
        uc.save_config(config, self.path)
        self.assertEqual(uc.system_prompt_override(self.path), "Soy joven Mauri")

    def test_empty_when_unset(self):
        uc.save_config(uc.default_config(), self.path)
        self.assertEqual(uc.system_prompt_override(self.path), "")

    def test_safe_when_file_missing(self):
        self.assertEqual(uc.system_prompt_override(self.path), "")

    def test_ares_context_prompt_injects_override(self):
        with patch("app.api.ares_edits.system_prompt_override", return_value="Soy joven Mauri"):
            prompt = _context_prompt("rename x", [])
        self.assertIn("[USER SYSTEM PROMPT]", prompt)
        self.assertIn("Soy joven Mauri", prompt)
        # No releva a A.R.E.S. de su rol/esquema base.
        self.assertIn("You are A.R.E.S.", prompt)

    def test_ares_context_prompt_without_override_is_unchanged(self):
        with patch("app.api.ares_edits.system_prompt_override", return_value=""):
            prompt = _context_prompt("rename x", [])
        self.assertFalse(prompt.startswith("[USER SYSTEM PROMPT]"))
        self.assertTrue(prompt.startswith("You are A.R.E.S."))

    def test_orchestrator_prepends_override(self):
        with patch("app.api.orchestrator.system_prompt_override", return_value="Soy joven Mauri"):
            result = orchestrator_api._con_system_prompt("¿qué hora es?")
        self.assertIn("Soy joven Mauri", result)
        self.assertTrue(result.rstrip().endswith("¿qué hora es?"))

    def test_orchestrator_without_override_matches_request_language(self):
        with patch("app.api.orchestrator.system_prompt_override", return_value=""):
            result = orchestrator_api._con_system_prompt("hola")
        self.assertIn("[RESPONSE LANGUAGE]", result)
        self.assertIn("respond in that same language", result)
        self.assertTrue(result.rstrip().endswith("hola"))


class UserConfigEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / ".geram-config.json"
        patcher = patch.object(user_config_api, "CONFIG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_generates_defaults_with_0600(self):
        result = asyncio.run(user_config_api.obtener_config())
        self.assertTrue(self.path.exists())
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(result["ui_theme"]["core_identity_view"], "core")
        self.assertIn("user_profile", result)
        self.assertIn("privacy_controls", result)
        self.assertEqual(result["onboarding"]["manual_version_seen"], 0)

    def test_post_validates_persists_and_keeps_0600(self):
        payload = uc.default_config()
        payload.user_profile.name = "Mauri"
        payload.user_profile.system_prompt_override = "llámame joven Mauri"
        payload.ui_theme.core_identity_view = "minimal"
        response = asyncio.run(user_config_api.actualizar_config(payload))
        self.assertEqual(response["status"], "ok")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        # Persistió de verdad en disco.
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["user_profile"]["name"], "Mauri")
        self.assertEqual(on_disk["ui_theme"]["core_identity_view"], "minimal")

    def test_post_payload_rejects_invalid_schema(self):
        # FastAPI valida el body con este mismo modelo antes de llamar al handler.
        with self.assertRaises(ValidationError):
            uc.GeramConfig.model_validate(
                {"ui_theme": {"core_identity_view": "hologram"}}
            )

    def test_manual_dismissal_is_monotonic_and_preserves_preferences(self):
        config = uc.default_config()
        config.user_profile.name = "Mauri"
        uc.save_config(config, self.path)

        first = asyncio.run(
            user_config_api.marcar_manual_visto(
                user_config_api.ManualSeenUpdate(version=2)
            )
        )
        second = asyncio.run(
            user_config_api.marcar_manual_visto(
                user_config_api.ManualSeenUpdate(version=1)
            )
        )
        saved = uc.load_config(self.path)

        self.assertEqual(first["manual_version_seen"], 2)
        self.assertEqual(second["manual_version_seen"], 2)
        self.assertEqual(saved.onboarding.manual_version_seen, 2)
        self.assertEqual(saved.user_profile.name, "Mauri")


if __name__ == "__main__":
    unittest.main()
