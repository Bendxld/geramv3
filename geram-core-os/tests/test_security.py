"""Focused tests for the local-network security boundary."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from app.core.security import require_local_origin, require_localhost


with (
    patch.dict(os.environ, {}, clear=True),
    patch("dotenv.load_dotenv", return_value=False),
    patch("pathlib.Path.mkdir"),
):
    from app.api import config as config_api
    from app.core import config as core_config


def _request_from(
    host: str,
    forwarded_for: str | None = None,
    origin: str | None = None,
) -> Request:
    headers = []
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    if origin:
        headers.append((b"origin", origin.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/config/keys",
            "headers": headers,
            "client": (host, 43210),
            "server": ("127.0.0.1", 8000),
        }
    )


class LocalhostGuardTests(unittest.TestCase):
    def test_localhost_addresses_are_allowed(self):
        for host in ("127.0.0.1", "::1"):
            with self.subTest(host=host):
                self.assertIsNone(require_localhost(_request_from(host)))

    def test_non_local_client_is_rejected_even_with_forwarded_header(self):
        request = _request_from("192.0.2.10", forwarded_for="127.0.0.1")
        with self.assertRaises(HTTPException) as raised:
            require_localhost(request)
        self.assertEqual(raised.exception.status_code, 403)

    def test_local_browser_origins_are_allowed(self):
        for origin in ("http://localhost:8000", "http://127.0.0.1:8000"):
            with self.subTest(origin=origin):
                self.assertIsNone(
                    require_local_origin(_request_from("127.0.0.1", origin=origin))
                )

    def test_non_browser_request_without_origin_is_allowed(self):
        self.assertIsNone(require_local_origin(_request_from("127.0.0.1")))

    def test_unexpected_browser_origin_is_rejected(self):
        request = _request_from("127.0.0.1", origin="https://example.invalid")
        with self.assertRaises(HTTPException) as raised:
            require_local_origin(request)
        self.assertEqual(raised.exception.status_code, 403)

    def test_config_routes_use_localhost_guard(self):
        protected_paths = {
            "/config/keys",
            "/config/providers",
            "/config/provider-keys",
            "/config/provider-keys/{credential_id}",
            "/config/restart",
        }
        for route in config_api.router.routes:
            if route.path not in protected_paths:
                continue
            dependency_calls = {
                dependency.call for dependency in route.dependant.dependencies
            }
            self.assertIn(require_localhost, dependency_calls)

    def test_mutating_config_routes_use_local_origin_guard(self):
        mutating_routes = {
            ("/config/keys", "POST"),
            ("/config/provider-keys", "POST"),
            ("/config/provider-keys/{credential_id}", "PATCH"),
            ("/config/provider-keys/{credential_id}", "DELETE"),
            ("/config/restart", "POST"),
        }
        for route in config_api.router.routes:
            route_methods = getattr(route, "methods", set())
            if not any(
                route.path == path and method in route_methods
                for path, method in mutating_routes
            ):
                continue
            dependency_calls = {
                dependency.call for dependency in route.dependant.dependencies
            }
            self.assertIn(require_local_origin, dependency_calls)

    def test_hud_websocket_rejects_remote_peers_and_unexpected_origins(self):
        from app.websocket.hud_socket import _local_websocket

        def socket(host, origin=None):
            headers = {} if origin is None else {"origin": origin}
            return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)

        self.assertTrue(_local_websocket(socket("127.0.0.1")))
        self.assertTrue(
            _local_websocket(
                socket("127.0.0.1", f"http://localhost:{core_config.settings.APP_PORT}")
            )
        )
        self.assertFalse(_local_websocket(socket("192.0.2.10")))
        self.assertFalse(
            _local_websocket(socket("127.0.0.1", "https://example.invalid"))
        )

    def test_agents_orchestrator_runtime_and_media_are_locally_guarded(self):
        from app.api import agents, instance, maintenance, orchestrator, runtime

        for router in (
            agents.router, instance.router, orchestrator.router,
            runtime.router, runtime.media_router, maintenance.router,
        ):
            for route in router.routes:
                dependencies = {
                    dependency.call for dependency in route.dependant.dependencies
                }
                self.assertIn(require_localhost, dependencies, route.path)

        mutable = {
            "/agents/load", "/agents/{agent_name}", "/orchestrator/route",
            "/api/runtime/state", "/api/media/attachments", "/api/media/audio",
            "/api/agents/roster/{agent_id}", "/roster/visibility",
            "/api/maintenance/backups", "/api/maintenance/restore",
        }
        routes = (
            agents.router.routes + instance.router.routes + orchestrator.router.routes
            + runtime.router.routes + runtime.media_router.routes
            + maintenance.router.routes
        )
        for route in routes:
            if route.path not in mutable or not (
                set(route.methods or ()) & {"POST", "PUT", "PATCH", "DELETE"}
            ):
                continue
            dependencies = {
                dependency.call for dependency in route.dependant.dependencies
            }
            self.assertIn(require_local_origin, dependencies, route.path)

    def test_orchestrator_prompt_and_rate_are_bounded(self):
        from pydantic import ValidationError
        from app.api.orchestrator import OrchestratorRequest
        from app.core.rate_limit import SlidingWindowLimiter

        with self.assertRaises(ValidationError):
            OrchestratorRequest(prompt="x" * 20_001, source="hud_local")
        with self.assertRaises(ValidationError):
            OrchestratorRequest(prompt="", source="hud_local")
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
        limiter.check("local")
        limiter.check("local")
        with self.assertRaises(HTTPException) as raised:
            limiter.check("local")
        self.assertEqual(raised.exception.status_code, 429)


class ConfigurationSecurityTests(unittest.TestCase):
    def test_provider_key_validation_error_does_not_echo_input(self):
        from app.main import safe_provider_key_validation_error

        submitted_value = "unit-test-sensitive-invalid-input"
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/config/provider-keys",
                "headers": [],
                "client": ("127.0.0.1", 43210),
                "server": ("127.0.0.1", 8000),
                "scheme": "http",
                "query_string": b"",
            }
        )
        error = RequestValidationError(
            [
                {
                    "type": "string_type",
                    "loc": ("body", "secret"),
                    "msg": "Input should be a valid string",
                    "input": submitted_value,
                }
            ]
        )
        response = asyncio.run(
            safe_provider_key_validation_error(request, error)
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(submitted_value, response.body.decode("utf-8"))

    def test_masked_response_does_not_return_full_value(self):
        test_value = "unit-test-sensitive-value"
        with tempfile.TemporaryDirectory() as temporary_directory:
            env_path = Path(temporary_directory) / ".env"
            env_path.write_text(f"OPENAI_API_KEY={test_value}\n")
            with patch.object(config_api, "ENV_PATH", env_path):
                response = asyncio.run(config_api.obtener_keys())

        self.assertNotEqual(response["OPENAI_API_KEY"], test_value)
        self.assertNotIn(test_value, response.values())
        self.assertTrue(response["OPENAI_API_KEY"].startswith("*"))

    def test_backend_default_host_is_loopback(self):
        self.assertEqual(core_config.DEFAULT_APP_HOST, "127.0.0.1")
        self.assertEqual(core_config.settings.APP_HOST, "127.0.0.1")

    def test_default_cors_origins_are_local(self):
        self.assertEqual(
            core_config.settings.CORS_ALLOWED_ORIGINS,
            ["http://localhost:8000", "http://127.0.0.1:8000"],
        )

    def test_wildcard_cors_override_is_rejected(self):
        with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": "*"}):
            origins = core_config._configured_local_cors_origins(8000)
        self.assertEqual(
            origins,
            ["http://localhost:8000", "http://127.0.0.1:8000"],
        )


if __name__ == "__main__":
    unittest.main()
