"""Tests para el sign-in local de GitHub (v3, Paso 3): el token se guarda con
permisos 0600, el estado refleja la sesión, el token NUNCA se devuelve, y el
sign-out lo borra. Sin red: _fetch_login se mockea."""

import asyncio
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api import github
from app.api.github import GithubTokenRequest


class GithubSignInTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.token_path = Path(self.temporary.name) / "data" / "github_token.json"
        patcher = patch.object(github, "TOKEN_PATH", self.token_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_is_disconnected_by_default(self):
        result = asyncio.run(github.github_status())
        self.assertEqual(result, {"connected": False, "login": None})

    def test_saving_token_stores_it_with_0600_and_never_echoes_it(self):
        async def fake_login(_token):
            return "octocat"
        with patch.object(github, "_fetch_login", fake_login):
            result = asyncio.run(github.guardar_token(GithubTokenRequest(token="ghp_secret123")))
        self.assertEqual(result, {"connected": True, "login": "octocat"})
        # Persistido con 0600.
        self.assertEqual(stat.S_IMODE(os.stat(self.token_path).st_mode), 0o600)
        # El token SÍ está en disco (para la integración) pero...
        on_disk = json.loads(self.token_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["token"], "ghp_secret123")
        # ...NUNCA aparece en las respuestas de la API.
        status = asyncio.run(github.github_status())
        self.assertNotIn("token", status)
        self.assertEqual(status, {"connected": True, "login": "octocat"})

    def test_offline_token_save_still_works_without_login(self):
        async def fake_login(_token):
            return None
        with patch.object(github, "_fetch_login", fake_login):
            result = asyncio.run(github.guardar_token(GithubTokenRequest(token="ghp_offline")))
        self.assertEqual(result, {"connected": True, "login": None})
        self.assertTrue(self.token_path.exists())

    def test_sign_out_removes_the_token(self):
        async def fake_login(_token):
            return None
        with patch.object(github, "_fetch_login", fake_login):
            asyncio.run(github.guardar_token(GithubTokenRequest(token="ghp_x")))
        self.assertTrue(self.token_path.exists())
        result = asyncio.run(github.cerrar_sesion())
        self.assertEqual(result, {"connected": False, "login": None})
        self.assertFalse(self.token_path.exists())
        self.assertEqual(asyncio.run(github.github_status())["connected"], False)


if __name__ == "__main__":
    unittest.main()
