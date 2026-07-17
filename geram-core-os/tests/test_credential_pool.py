"""Credential-pool storage, selection, rotation, and API safety tests."""

import asyncio
import json
import os
import sqlite3
import stat
import tempfile
import unittest

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


with (
    patch.dict(os.environ, {}, clear=True),
    patch("dotenv.load_dotenv", return_value=False),
    patch("pathlib.Path.mkdir"),
):
    from app.api import config as config_api
    from app.core.config import Settings
    from app.core.credential_pool import (
        CredentialPoolManager,
        CredentialPoolValidationError,
    )
    from app.core.providers.base import (
        ProviderConfigurationError,
        ProviderResult,
        ProviderSpec,
        ProviderUnavailableError,
    )
    from app.core.providers.registry import ProviderRegistry


class FakeClock:
    def __init__(self, value: float = 1_700_000_000.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SequencedProvider:
    def __init__(self, provider_id: str, outcomes=None):
        self.spec = ProviderSpec(
            provider_id=provider_id,
            display_label=provider_id.title(),
            default_model=f"{provider_id}-default-model",
        )
        self.outcomes = list(outcomes or [])
        self.calls = 0

    async def generate(self, request, credential):
        self.calls += 1
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        return ProviderResult(
            text=f"response-from-{self.spec.provider_id}",
            provider_id=self.spec.provider_id,
            model=request.model,
        )


class CredentialPoolTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.clock = FakeClock()
        self.database_path = (
            Path(self.temporary_directory.name)
            / "credentials"
            / "credential_pool.sqlite3"
        )
        self.pool = CredentialPoolManager(
            self.database_path,
            clock=self.clock,
            random_source=lambda: 0.5,
        )

    def add(
        self,
        label: str,
        *,
        provider: str = "openai",
        priority: int = 100,
        enabled: bool = True,
        cap: int | None = None,
    ) -> dict[str, object]:
        return self.pool.add_credential(
            provider,
            label,
            f"unit-test-secret-for-{provider}-{label}",
            priority=priority,
            enabled=enabled,
            daily_request_cap=cap,
        )


class CredentialPoolStorageTests(CredentialPoolTestCase):
    def test_default_store_is_outside_repository_and_static_tree(self):
        configuration = Settings({}, create_runtime_dirs=False)
        repository_root = Path(__file__).resolve().parent.parent
        self.assertFalse(configuration.CREDENTIAL_STORE_PATH.is_relative_to(repository_root))
        self.assertFalse(
            configuration.CREDENTIAL_STORE_PATH.is_relative_to(repository_root / "static")
        )

    def test_multiple_credentials_and_safe_metadata(self):
        first = self.add("project-one")
        second = self.add("project-two")
        metadata = self.pool.list_safe_metadata("openai")
        rendered = json.dumps(metadata, sort_keys=True)

        self.assertEqual(len(metadata), 2)
        self.assertEqual(
            {item["credential_id"] for item in metadata},
            {first["credential_id"], second["credential_id"]},
        )
        self.assertNotIn("unit-test-secret", rendered)
        self.assertTrue(all(str(item["fingerprint"]).startswith("fp_") for item in metadata))
        self.assertTrue(all("secret" not in key for item in metadata for key in item))

    def test_file_permissions_and_transactional_writes(self):
        self.add("atomic")
        database_mode = stat.S_IMODE(self.database_path.stat().st_mode)
        directory_mode = stat.S_IMODE(self.database_path.parent.stat().st_mode)
        self.assertEqual(database_mode, 0o600)
        self.assertEqual(directory_mode, 0o700)

        connection = sqlite3.connect(self.database_path)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            metadata_count = connection.execute(
                "SELECT COUNT(*) FROM credential_metadata"
            ).fetchone()[0]
            secret_count = connection.execute(
                "SELECT COUNT(*) FROM credential_secrets"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(integrity, "ok")
        self.assertEqual(metadata_count, secret_count)

    def test_initialization_and_sidecars_remain_owner_only(self):
        previous_umask = os.umask(0)
        try:
            self.pool._ensure_database()
        finally:
            os.umask(previous_umask)
        self.assertEqual(stat.S_IMODE(self.database_path.stat().st_mode), 0o600)

        sidecars = [
            Path(f"{self.database_path}{suffix}")
            for suffix in ("-journal", "-wal", "-shm")
        ]
        for sidecar in sidecars:
            descriptor = os.open(sidecar, os.O_CREAT | os.O_WRONLY, 0o644)
            os.close(descriptor)
        self.pool._ensure_database()
        for sidecar in sidecars:
            self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)

    def test_hmac_key_is_random_persistent_and_not_public_metadata(self):
        synthetic_secret = "unit-test-fingerprint-source"
        created = self.pool.add_credential(
            "gemini",
            "stable fingerprint",
            synthetic_secret,
        )
        restarted_pool = CredentialPoolManager(self.database_path, clock=self.clock)
        restarted = restarted_pool.list_safe_metadata("gemini")[0]
        self.assertEqual(created["fingerprint"], restarted["fingerprint"])

        connection = sqlite3.connect(self.database_path)
        try:
            hmac_key = connection.execute(
                "SELECT value FROM pool_settings WHERE key = ?",
                ("fingerprint_salt",),
            ).fetchone()[0]
        finally:
            connection.close()
        rendered = json.dumps(restarted, sort_keys=True)
        self.assertNotEqual(hmac_key, synthetic_secret)
        self.assertNotIn(hmac_key, rendered)
        self.assertNotIn(synthetic_secret, str(created["fingerprint"]))

    def test_failed_secret_insert_rolls_back_metadata(self):
        self.pool._ensure_database()
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """
                CREATE TRIGGER reject_test_secret
                BEFORE INSERT ON credential_secrets
                BEGIN
                    SELECT RAISE(ABORT, 'test transaction failure');
                END;
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(sqlite3.IntegrityError):
            self.add("rollback")

        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM credential_metadata"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def test_replace_remove_and_invalid_enable_policy(self):
        created = self.add("replaceable")
        credential_id = str(created["credential_id"])
        self.pool.record_failure(credential_id, "authentication")
        invalid = self.pool.list_safe_metadata("openai")[0]
        self.assertTrue(invalid["invalid"])
        self.assertFalse(invalid["enabled"])

        with self.assertRaises(CredentialPoolValidationError):
            self.pool.enable_credential(credential_id)

        replaced = self.pool.replace_credential(
            credential_id,
            "unit-test-replacement-secret",
        )
        self.assertFalse(replaced["invalid"])
        self.assertFalse(replaced["enabled"])
        enabled = self.pool.enable_credential(credential_id)
        self.assertTrue(enabled["enabled"])

        self.pool.remove_credential(credential_id)
        self.assertEqual(self.pool.list_safe_metadata("openai"), [])
        connection = sqlite3.connect(self.database_path)
        try:
            secret_count = connection.execute(
                "SELECT COUNT(*) FROM credential_secrets"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(secret_count, 0)


class CredentialPoolSelectionTests(CredentialPoolTestCase):
    def test_fair_round_robin_inside_same_priority(self):
        first = self.add("first")
        second = self.add("second")

        leases = [asyncio.run(self.pool.acquire("openai")) for _ in range(3)]
        lease_ids = [lease.credential_id for lease in leases if lease is not None]
        self.assertEqual(set(lease_ids[:2]), {first["credential_id"], second["credential_id"]})
        self.assertEqual(lease_ids[2], lease_ids[0])

    def test_priority_precedes_round_robin(self):
        preferred = self.add("preferred", priority=10)
        self.add("secondary", priority=20)
        leases = [asyncio.run(self.pool.acquire("openai")) for _ in range(2)]
        self.assertTrue(
            all(lease.credential_id == preferred["credential_id"] for lease in leases)
        )

    def test_concurrent_acquisition_remains_fair(self):
        first = self.add("first")
        second = self.add("second")

        async def acquire_many():
            return await asyncio.gather(
                *(self.pool.acquire("openai") for _ in range(10))
            )

        leases = asyncio.run(acquire_many())
        counts = {
            first["credential_id"]: 0,
            second["credential_id"]: 0,
        }
        for lease in leases:
            counts[lease.credential_id] += 1
        self.assertEqual(set(counts.values()), {5})

    def test_rate_limit_cooldown_and_rotation(self):
        first = self.add("first")
        second = self.add("second")
        lease = asyncio.run(self.pool.acquire("openai"))
        self.pool.record_failure(lease.credential_id, "rate_limit")

        rotated = asyncio.run(self.pool.acquire("openai"))
        self.assertNotEqual(rotated.credential_id, lease.credential_id)
        self.assertEqual(
            {rotated.credential_id, lease.credential_id},
            {first["credential_id"], second["credential_id"]},
        )
        metadata = self.pool.list_safe_metadata("openai")
        first_metadata = next(
            item for item in metadata if item["credential_id"] == lease.credential_id
        )
        self.assertEqual(first_metadata["health_status"], "cooldown")

    def test_retry_after_is_honored_within_bound(self):
        created = self.add("retry-after")
        self.pool.record_failure(
            str(created["credential_id"]),
            "rate_limit",
            retry_after_seconds=120,
        )
        metadata = self.pool.list_safe_metadata("openai")[0]
        expected = (
            datetime.fromtimestamp(self.clock.value + 120, timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        self.assertEqual(metadata["cooldown_until"], expected)

    def test_timeout_and_upstream_failures_rotate(self):
        first = self.add("first")
        second = self.add("second")
        first_lease = asyncio.run(self.pool.acquire("openai"))
        self.pool.record_failure(first_lease.credential_id, "timeout")
        second_lease = asyncio.run(self.pool.acquire("openai"))
        self.assertNotEqual(second_lease.credential_id, first_lease.credential_id)
        self.assertEqual(
            {first_lease.credential_id, second_lease.credential_id},
            {first["credential_id"], second["credential_id"]},
        )
        self.pool.record_failure(second_lease.credential_id, "upstream")
        self.assertIsNone(asyncio.run(self.pool.acquire("openai")))
        self.assertNotEqual(first["credential_id"], second["credential_id"])

    def test_disabled_cooldown_and_daily_cap_credentials_are_skipped(self):
        disabled = self.add("disabled", priority=1, enabled=False)
        capped = self.add("capped", priority=2, cap=1)
        available = self.add("available", priority=2)

        first = asyncio.run(self.pool.acquire("openai"))
        second = asyncio.run(self.pool.acquire("openai"))
        third = asyncio.run(self.pool.acquire("openai"))

        self.assertEqual(
            {first.credential_id, second.credential_id},
            {capped["credential_id"], available["credential_id"]},
        )
        self.assertEqual(third.credential_id, available["credential_id"])
        metadata = self.pool.list_safe_metadata("openai")
        disabled_metadata = next(
            item for item in metadata if item["credential_id"] == disabled["credential_id"]
        )
        capped_metadata = next(
            item for item in metadata if item["credential_id"] == capped["credential_id"]
        )
        self.assertEqual(disabled_metadata["health_status"], "disabled")
        self.assertEqual(capped_metadata["health_status"], "daily_cap_reached")


class CredentialPoolRoutingTests(CredentialPoolTestCase):
    def settings(self, **overrides) -> Settings:
        values = {
            "OPENAI_API_KEY": "legacy-openai-test-secret",
            "GEMINI_API_KEY": "legacy-gemini-test-secret",
            "GROQ_API_KEY": "legacy-groq-test-secret",
        }
        values.update(overrides)
        return Settings(values, create_runtime_dirs=False)

    def test_authentication_failure_invalidates_and_rotates(self):
        first = self.add("first")
        self.add("second")
        provider = SequencedProvider(
            "openai",
            outcomes=[
                ProviderUnavailableError(
                    "openai",
                    "Provider authentication failed",
                    reason="authentication",
                ),
                None,
            ],
        )
        registry = ProviderRegistry([provider], credential_pool=self.pool)

        dispatch = asyncio.run(
            registry.generate_for_role("ares", "hello", self.settings())
        )

        self.assertEqual(provider.calls, 2)
        self.assertEqual(dispatch.result["text"], "response-from-openai")
        metadata = self.pool.list_safe_metadata("openai")
        invalid = [item for item in metadata if item["invalid"]]
        self.assertEqual(len(invalid), 1)
        self.assertFalse(invalid[0]["enabled"])

    def test_empty_pool_uses_legacy_credential_without_persisting_it(self):
        provider = SequencedProvider("openai")
        registry = ProviderRegistry([provider], credential_pool=self.pool)
        dispatch = asyncio.run(
            registry.generate_for_role("ares", "hello", self.settings())
        )
        self.assertEqual(dispatch.result["text"], "response-from-openai")
        self.assertEqual(provider.calls, 1)
        self.assertFalse(self.database_path.exists())

    def test_invalid_request_does_not_rotate(self):
        self.add("first")
        self.add("second")
        provider = SequencedProvider(
            "openai",
            outcomes=[
                ProviderConfigurationError(
                    "openai",
                    "Provider rejected the request or model configuration",
                )
            ],
        )
        registry = ProviderRegistry([provider], credential_pool=self.pool)
        dispatch = asyncio.run(
            registry.generate_for_role("ares", "hello", self.settings())
        )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            dispatch.result["error_code"],
            "provider_configuration_error",
        )

    def test_maximum_attempts_are_enforced(self):
        for label in ("one", "two", "three"):
            self.add(label)
        provider = SequencedProvider(
            "openai",
            outcomes=[
                ProviderUnavailableError(
                    "openai",
                    "Provider request timed out",
                    reason="timeout",
                )
                for _ in range(3)
            ],
        )
        registry = ProviderRegistry([provider], credential_pool=self.pool)
        configuration = self.settings(CREDENTIAL_POOL_MAX_ATTEMPTS="2")
        dispatch = asyncio.run(
            registry.generate_for_role("ares", "hello", configuration)
        )
        self.assertEqual(provider.calls, 2)
        self.assertEqual(dispatch.result["error_code"], "provider_unavailable")

    def test_provider_fallback_runs_once_after_pool_exhaustion(self):
        self.add("one", provider="gemini")
        self.add("two", provider="gemini")
        primary = SequencedProvider(
            "gemini",
            outcomes=[
                ProviderUnavailableError(
                    "gemini",
                    "Provider request timed out",
                    reason="timeout",
                ),
                ProviderUnavailableError(
                    "gemini",
                    "Provider service is unavailable",
                    reason="upstream",
                ),
            ],
        )
        fallback = SequencedProvider("groq")
        registry = ProviderRegistry(
            [primary, fallback],
            credential_pool=self.pool,
        )
        configuration = self.settings(
            IRIS_PROVIDER="gemini",
            IRIS_FALLBACK_PROVIDER="groq",
        )

        dispatch = asyncio.run(
            registry.generate_for_role("iris", "hello", configuration)
        )

        self.assertEqual(primary.calls, 2)
        self.assertEqual(fallback.calls, 1)
        self.assertTrue(dispatch.metadata["fallback_used"])
        self.assertEqual(dispatch.metadata["provider"], "groq")


class CredentialPoolApiTests(CredentialPoolTestCase):
    def test_api_never_returns_submitted_or_replacement_secret(self):
        original = "unit-test-api-original-secret"
        replacement = "unit-test-api-replacement-secret"
        with patch.object(config_api, "credential_pool_manager", self.pool):
            created = asyncio.run(
                config_api.crear_credencial_proveedor(
                    config_api.ProviderCredentialCreate(
                        provider="openai",
                        label="api project",
                        secret=original,
                    )
                )
            )
            credential_id = created["credential"]["credential_id"]
            listed = asyncio.run(config_api.listar_credenciales_proveedor())
            updated = asyncio.run(
                config_api.actualizar_credencial_proveedor(
                    credential_id,
                    config_api.ProviderCredentialPatch(secret=replacement),
                )
            )

        rendered = json.dumps(
            {"created": created, "listed": listed, "updated": updated},
            sort_keys=True,
        )
        self.assertNotIn(original, rendered)
        self.assertNotIn(replacement, rendered)
        self.assertEqual(len(listed["credentials"]), 1)

    def test_api_updates_safe_metadata_and_removes_record(self):
        with patch.object(config_api, "credential_pool_manager", self.pool):
            created = asyncio.run(
                config_api.crear_credencial_proveedor(
                    config_api.ProviderCredentialCreate(
                        provider="gemini",
                        label="first label",
                        secret="unit-test-api-crud-secret",
                    )
                )
            )
            credential_id = created["credential"]["credential_id"]
            updated = asyncio.run(
                config_api.actualizar_credencial_proveedor(
                    credential_id,
                    config_api.ProviderCredentialPatch(
                        label="renamed project",
                        enabled=False,
                        priority=25,
                        daily_request_cap=50,
                    ),
                )
            )
            deleted = asyncio.run(
                config_api.eliminar_credencial_proveedor(credential_id)
            )
            listed = asyncio.run(
                config_api.listar_credenciales_proveedor("gemini")
            )

        self.assertEqual(updated["credential"]["label"], "renamed project")
        self.assertFalse(updated["credential"]["enabled"])
        self.assertEqual(updated["credential"]["priority"], 25)
        self.assertEqual(updated["credential"]["daily_request_cap"], 50)
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(listed["credentials"], [])

    def test_unknown_id_and_storage_failures_are_sanitized(self):
        unknown_id = "00000000-0000-0000-0000-000000000000"
        with patch.object(config_api, "credential_pool_manager", self.pool):
            with self.assertRaises(config_api.HTTPException) as missing:
                asyncio.run(
                    config_api.eliminar_credencial_proveedor(unknown_id)
                )
        self.assertEqual(missing.exception.status_code, 404)
        self.assertNotIn(unknown_id, str(missing.exception.detail))

        with patch.object(
            self.pool,
            "list_safe_metadata",
            side_effect=sqlite3.OperationalError("synthetic storage failure"),
        ):
            with patch.object(config_api, "credential_pool_manager", self.pool):
                with self.assertRaises(config_api.HTTPException) as unavailable:
                    asyncio.run(config_api.listar_credenciales_proveedor())
        self.assertEqual(unavailable.exception.status_code, 503)
        self.assertNotIn("synthetic", str(unavailable.exception.detail))


if __name__ == "__main__":
    unittest.main()
