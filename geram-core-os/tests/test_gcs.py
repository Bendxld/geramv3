"""
Tests for the GERAM Core System (GCS) — the AI Operating Environment core.

Covers the six pillars end to end, offline, with an isolated LOCAL_DATA_DIR so
nothing touches the real user data directory:

  * Permission Registry — catalog, three-state decide, fail-closed.
  * Skill System — system vs custom, untrusted-content handling, traversal.
  * Local Skill Retriever — exact-match priority, offline short-circuit.
  * Integration Hub — sanitized status, available/connected/authorized gating.
  * Agent Factory — CRUD, referential validation, profile ownership.
  * Context Builder — sanitization, least privilege, memory state.
  * Router — endpoint behavior + localhost guard registration.
  * Orchestrator — offline-first local skill short-circuit (no provider call).
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import Depends, HTTPException
from pydantic import ValidationError

from app.core.config import settings
from app.core.gcs import storage
from app.core.gcs.agent_factory import AgentDefinition, AgentFactory, AgentValidationError
from app.core.gcs.context_builder import ContextBuilder, ContextBuilderError
from app.core.gcs.integrations import (
    IntegrationHub, NotionAdapter, ObsidianAdapter, SpotifyAdapter,
)
from app.core.gcs.memory import MemoryManager
from app.core.gcs.permissions import Permission, permission_registry
from app.core.gcs.skill_retriever import SkillRetriever
from app.core.gcs.skills import Skill, SkillStore
from app.core.gcs.storage import StorageError


class _IsolatedDataDirTest(unittest.TestCase):
    """Base: redirect LOCAL_DATA_DIR to a throwaway temp dir per test."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        patcher = patch.object(settings, "LOCAL_DATA_DIR", Path(self.temporary.name))
        patcher.start()
        self.addCleanup(patcher.stop)


# ----------------------------------------------------------------------
# Permission Registry
# ----------------------------------------------------------------------
class PermissionRegistryTests(unittest.TestCase):
    def test_catalog_has_every_documented_permission(self):
        slugs = {spec.permission.value for spec in permission_registry.catalog()}
        self.assertEqual(
            slugs,
            {
                "read", "write", "terminal", "test_runner", "internet",
                "spotify", "notion", "session_memory", "permanent_memory",
                "telegram", "supabase", "calendar", "obsidian",
            },
        )

    def test_read_is_allowed_write_requires_approval(self):
        self.assertEqual(permission_registry.decide(["read"], "read").outcome, "allowed")
        decision = permission_registry.decide(["read", "write"], "write")
        self.assertEqual(decision.outcome, "approval_required")
        self.assertTrue(decision.approval_required)

    def test_missing_grant_is_denied(self):
        self.assertEqual(permission_registry.decide(["read"], "terminal").outcome, "denied")

    def test_unknown_permission_fails_closed(self):
        self.assertEqual(permission_registry.decide(["read"], "root").outcome, "denied")
        self.assertFalse(permission_registry.has(["read"], "not-a-real-perm"))
        # Junk inside the grant list is ignored, not trusted.
        self.assertFalse(permission_registry.has(["../../etc"], "read"))

    def test_normalize_many_rejects_unknown(self):
        with self.assertRaises(ValueError):
            permission_registry.normalize_many(["read", "bogus"])


# ----------------------------------------------------------------------
# Storage helpers
# ----------------------------------------------------------------------
class StorageTests(_IsolatedDataDirTest):
    def test_ids_are_traversal_proof(self):
        for bad in ["..", "../x", "a/b", "/etc/passwd", "A B", "", "x" * 65]:
            with self.assertRaises(StorageError):
                storage.validate_id(bad)

    def test_document_path_cannot_escape_directory(self):
        directory = storage.gcs_data_dir("skills", "custom")
        with self.assertRaises(StorageError):
            storage.document_path(directory, "../escape")

    def test_atomic_write_is_owner_only(self):
        directory = storage.gcs_data_dir("skills", "custom")
        path = storage.document_path(directory, "sample")
        storage.write_json_atomic_0600(path, {"ok": True})
        import os
        import stat
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


# ----------------------------------------------------------------------
# Skill System
# ----------------------------------------------------------------------
class SkillSystemTests(_IsolatedDataDirTest):
    def setUp(self):
        super().setUp()
        self.store = SkillStore()

    def test_system_skills_present_and_trusted(self):
        system = {s.id: s for s in self.store.list_system()}
        self.assertIn("html-boilerplate", system)
        self.assertEqual(system["html-boilerplate"].origin, "system")

    def test_custom_skill_roundtrip(self):
        skill = Skill(
            id="my-snippet", name="My Snippet", triggers=["mine"],
            permissions=["read"], body="hello",
        )
        self.store.save_custom(skill)
        loaded = self.store.get("my-snippet")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.body, "hello")
        self.assertIn("my-snippet", [s.id for s in self.store.list_custom()])

    def test_cannot_shadow_or_delete_system_skill(self):
        with self.assertRaises(StorageError):
            self.store.save_custom(Skill(id="html-boilerplate", name="fake"))
        with self.assertRaises(StorageError):
            self.store.delete_custom("html-boilerplate")

    def test_custom_content_is_untrusted_origin_forced(self):
        # A crafted file claiming origin=system must load back as custom.
        directory = storage.gcs_data_dir("skills", "custom")
        path = storage.document_path(directory, "sneaky")
        storage.write_json_atomic_0600(
            path,
            {"id": "sneaky", "name": "Sneaky", "origin": "system", "permissions": [], "triggers": []},
        )
        loaded = self.store.get("sneaky")
        self.assertEqual(loaded.origin, "custom")

    def test_unknown_permission_rejected(self):
        with self.assertRaises(ValidationError):
            Skill(id="bad", name="Bad", permissions=["root"])

    def test_delete_returns_false_when_absent(self):
        self.assertFalse(self.store.delete_custom("nope"))


# ----------------------------------------------------------------------
# Local Skill Retriever
# ----------------------------------------------------------------------
class SkillRetrieverTests(_IsolatedDataDirTest):
    def setUp(self):
        super().setUp()
        self.retriever = SkillRetriever(SkillStore())

    def test_exact_trigger_wins_and_is_handled_locally(self):
        result = self.retriever.retrieve("html", profile="ares")
        self.assertTrue(result.handled_locally)
        self.assertEqual(result.best.skill.id, "html-boilerplate")

    def test_unrelated_query_not_handled_locally(self):
        result = self.retriever.retrieve("quantum chromodynamics zzz")
        self.assertFalse(result.handled_locally)
        self.assertEqual(result.matches, [])

    def test_profile_filtering(self):
        # All system skills are ares-profile; an iris query should not match them.
        result = self.retriever.retrieve("html", profile="iris")
        self.assertFalse(result.handled_locally)

    def test_empty_query_is_safe(self):
        result = self.retriever.retrieve("   ")
        self.assertFalse(result.handled_locally)


# ----------------------------------------------------------------------
# Integration Hub
# ----------------------------------------------------------------------
class IntegrationHubTests(unittest.TestCase):
    def setUp(self):
        self.hub = IntegrationHub([SpotifyAdapter(), NotionAdapter()])

    def test_sanitized_status_never_leaks_secrets(self):
        for status in self.hub.list_integrations():
            self.assertNotIn("token", str(status).lower())
            self.assertIn(status["state"], {"available", "connected"})

    def test_unknown_integration_and_action_denied(self):
        self.assertEqual(
            self.hub.invoke("nope", "x", {}, granted=[], approved=False).status, "denied"
        )
        with patch.object(SpotifyAdapter, "is_connected", return_value=True), patch(
            "app.core.gcs.integrations._request_json", return_value={}
        ):
            self.assertEqual(
                self.hub.invoke("spotify", "explode", {}, granted=["spotify"], approved=False).status,
                "denied",
            )

    def test_not_connected_is_unavailable(self):
        with patch.object(SpotifyAdapter, "is_connected", return_value=False):
            result = self.hub.invoke("spotify", "status", {}, granted=["spotify"], approved=False)
            self.assertEqual(result.status, "unavailable")

    def test_permission_gating(self):
        with patch.object(SpotifyAdapter, "is_connected", return_value=True), patch(
            "app.core.gcs.integrations._request_json", return_value={}
        ):
            # No permission -> denied.
            self.assertEqual(
                self.hub.invoke("spotify", "status", {}, granted=[], approved=False).status,
                "denied",
            )
            # Read-only action with permission -> ok immediately.
            self.assertEqual(
                self.hub.invoke("spotify", "status", {}, granted=["spotify"], approved=False).status,
                "ok",
            )
            # Mutating action without approval -> approval_required.
            self.assertEqual(
                self.hub.invoke("spotify", "play", {}, granted=["spotify"], approved=False).status,
                "approval_required",
            )
            # Mutating action WITH approval reaches the real adapter boundary.
            ok = self.hub.invoke("spotify", "play", {}, granted=["spotify"], approved=True)
            self.assertEqual(ok.status, "ok")
            self.assertEqual(ok.detail["playback"], "playing")

    def test_notion_connection_reflects_env_presence_only(self):
        with patch.object(settings, "NOTION_API_KEY", "secret-value"), patch.object(
            settings, "NOTION_DATABASE_ID", "database-id"
        ):
            status = {s["id"]: s for s in self.hub.list_integrations()}["notion"]
            self.assertEqual(status["state"], "connected")
            self.assertNotIn("secret-value", str(status))

    def test_obsidian_write_and_read_are_confined_to_the_vault(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "OBSIDIAN_VAULT_PATH", directory
        ):
            hub = IntegrationHub([ObsidianAdapter()])
            written = hub.invoke(
                "obsidian", "write_note", {"path": "notes/hello", "content": "hola"},
                granted=["obsidian"], approved=True,
            )
            self.assertEqual(written.status, "ok")
            read = hub.invoke(
                "obsidian", "read_note", {"path": "notes/hello.md"},
                granted=["obsidian"], approved=False,
            )
            self.assertEqual(read.detail["content"], "hola")
            denied = hub.invoke(
                "obsidian", "read_note", {"path": "../outside.md"},
                granted=["obsidian"], approved=False,
            )
            self.assertEqual(denied.status, "unavailable")


# ----------------------------------------------------------------------
# Agent Factory
# ----------------------------------------------------------------------
class AgentFactoryTests(_IsolatedDataDirTest):
    def setUp(self):
        super().setUp()
        self.factory = AgentFactory()

    def test_system_example_agent_is_helper_not_profile(self):
        mustafa = self.factory.get("mustafa")
        self.assertIsNotNone(mustafa)
        self.assertIn(mustafa.profile, ("iris", "ares"))
        self.assertEqual(mustafa.origin, "system")

    def test_custom_agent_crud(self):
        agent = AgentDefinition(
            id="helper1", name="Helper", profile="ares",
            skills=["html-boilerplate"], permissions=["read", "write"],
        )
        self.factory.save_custom(agent)
        self.assertIsNotNone(self.factory.get("helper1"))
        self.assertTrue(self.factory.delete_custom("helper1"))
        self.assertIsNone(self.factory.get("helper1"))

    def test_profile_must_be_iris_or_ares(self):
        with self.assertRaises(ValidationError):
            AgentDefinition(id="x", name="X", profile="any")

    def test_reference_validation_rejects_unknown_skill(self):
        with self.assertRaises(AgentValidationError):
            self.factory.save_custom(
                AgentDefinition(id="a", name="A", profile="ares", skills=["ghost"])
            )

    def test_reference_validation_rejects_incompatible_skill_profile(self):
        # html-boilerplate is ares-only; assigning to an iris agent must fail.
        with self.assertRaises(AgentValidationError):
            self.factory.save_custom(
                AgentDefinition(id="a", name="A", profile="iris", skills=["html-boilerplate"])
            )

    def test_integration_requires_matching_permission(self):
        with self.assertRaises(AgentValidationError):
            self.factory.save_custom(
                AgentDefinition(
                    id="a", name="A", profile="ares",
                    integrations=["spotify"], permissions=["read"],
                )
            )
        # With the permission it validates.
        self.factory.save_custom(
            AgentDefinition(
                id="a", name="A", profile="ares",
                integrations=["spotify"], permissions=["read", "spotify"],
            )
        )

    def test_cannot_shadow_or_delete_system_agent(self):
        with self.assertRaises(StorageError):
            self.factory.save_custom(AgentDefinition(id="mustafa", name="fake", profile="ares"))
        with self.assertRaises(StorageError):
            self.factory.delete_custom("mustafa")


# ----------------------------------------------------------------------
# Context Builder
# ----------------------------------------------------------------------
class ContextBuilderTests(_IsolatedDataDirTest):
    def setUp(self):
        super().setUp()
        self.builder = ContextBuilder()

    def test_build_for_system_agent_is_sanitized(self):
        context = self.builder.build("ares", "mustafa").as_dict()
        self.assertEqual(context["profile"], "ares")
        self.assertEqual(context["permissions"], ["read", "write", "terminal"])
        self.assertIn("html-boilerplate", [s["id"] for s in context["skills"]])
        # No secret material anywhere in the bundle.
        blob = str(context).lower()
        for forbidden in ("api_key", "token", "secret", "password"):
            self.assertNotIn(forbidden, blob)

    def test_bare_profile_has_least_privilege(self):
        context = self.builder.build("iris").as_dict()
        self.assertEqual(context["permissions"], [])
        self.assertEqual(context["skills"], [])
        self.assertEqual(context["tools"], [])

    def test_invalid_profile_and_unknown_agent(self):
        with self.assertRaises(ContextBuilderError):
            self.builder.build("root")
        with self.assertRaises(ContextBuilderError):
            self.builder.build("ares", "does-not-exist")

    def test_agent_cannot_be_used_from_wrong_profile(self):
        with self.assertRaises(ContextBuilderError) as caught:
            self.builder.build("iris", "mustafa")
        self.assertEqual(caught.exception.code, "profile_mismatch")

    def test_per_user_roster_state_blocks_context(self):
        with patch("app.core.gcs.context_builder.agent_roster_store.is_enabled", return_value=False):
            with self.assertRaises(ContextBuilderError) as caught:
                self.builder.build("ares", "mustafa")
        self.assertEqual(caught.exception.code, "agent_disabled")

    def test_integration_authorized_reflects_permission_and_connection(self):
        # mustafa holds no spotify/notion permission -> not authorized.
        context = self.builder.build("ares", "mustafa").as_dict()
        for integration in context["integrations"]:
            self.assertFalse(integration["authorized"])

    def test_memory_state_defaults_conservative(self):
        context = self.builder.build("ares", "mustafa").as_dict()
        self.assertTrue(context["memory"]["session"]["enabled"])
        self.assertFalse(context["memory"]["permanent"]["enabled"])
        self.assertFalse(context["memory"]["permanent"]["auto_save"])


# ----------------------------------------------------------------------
# Memory
# ----------------------------------------------------------------------
class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.memory = MemoryManager()

    def test_session_memory_is_bounded_and_ephemeral(self):
        for index in range(150):
            self.memory.remember_session("s1", f"note {index}")
        notes = self.memory.recall_session("s1")
        self.assertLessEqual(len(notes), 100)
        self.assertEqual(notes[-1], "note 149")
        self.memory.forget_session("s1")
        self.assertEqual(self.memory.recall_session("s1"), [])

    def test_permanent_memory_requires_permission(self):
        self.assertFalse(self.memory.permanent_enabled([]))
        self.assertTrue(self.memory.permanent_enabled(["permanent_memory"]))
        state = self.memory.memory_state(["permanent_memory"])
        self.assertTrue(state["permanent"]["enabled"])
        self.assertFalse(state["permanent"]["auto_save"])


# ----------------------------------------------------------------------
# Router endpoints (unit-level, matching repo style)
# ----------------------------------------------------------------------
class GcsRouterTests(_IsolatedDataDirTest):
    def test_router_is_localhost_guarded(self):
        from app.api import gcs
        from app.core.security import require_localhost
        dependencies = [d.dependency for d in gcs.router.dependencies]
        self.assertIn(require_localhost, dependencies)

    def test_permissions_endpoint(self):
        from app.api import gcs
        result = asyncio.run(gcs.list_permissions())
        self.assertEqual(len(result["permissions"]), 13)

    def test_retrieve_endpoint_offline(self):
        from app.api import gcs
        payload = gcs.RetrieveRequest(query="html", profile="ares")
        result = asyncio.run(gcs.retrieve_skill(payload))
        self.assertTrue(result["handled_locally"])
        self.assertEqual(result["skill_used"], "html-boilerplate")

    def test_save_and_get_skill_endpoint(self):
        from app.api import gcs
        saved = asyncio.run(
            gcs.save_skill({"id": "endpoint-skill", "name": "E", "permissions": ["read"]})
        )
        self.assertEqual(saved["status"], "ok")
        fetched = asyncio.run(gcs.get_skill("endpoint-skill"))
        self.assertEqual(fetched["id"], "endpoint-skill")

    def test_context_endpoint(self):
        from app.api import gcs
        payload = gcs.ContextRequest(profile="ares", agent_id="mustafa")
        result = asyncio.run(gcs.build_context(payload))
        self.assertEqual(result["profile"], "ares")

    def test_integration_invoke_derives_permission_from_agent(self):
        from app.api import gcs
        # mustafa has no spotify permission -> denied regardless of request.
        payload = gcs.InvokeIntegrationRequest(action="status", agent_id="mustafa")
        with patch.object(SpotifyAdapter, "is_connected", return_value=True):
            result = asyncio.run(gcs.invoke_integration("spotify", payload))
        self.assertEqual(result["status"], "denied")

    def test_disabled_agent_cannot_invoke_an_integration(self):
        from app.api import gcs
        payload = gcs.InvokeIntegrationRequest(action="status", agent_id="mustafa")
        with patch.object(gcs.agent_roster_store, "is_enabled", return_value=False):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(gcs.invoke_integration("spotify", payload))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "agent_disabled")


# ----------------------------------------------------------------------
# Orchestrator offline-first integration
# ----------------------------------------------------------------------
class OrchestratorOfflineTests(_IsolatedDataDirTest):
    def test_local_skill_short_circuits_without_provider(self):
        from app.api import orchestrator
        mock = AsyncMock()
        with patch.object(orchestrator.provider_registry, "generate_for_role", new=mock):
            response = asyncio.run(
                orchestrator.procesar_orquestacion(
                    "html", "hud_local", force_mode="ares", prefer_local_skills=True
                )
            )
        mock.assert_not_awaited()
        self.assertEqual(response.metadata["provider"], "local")
        self.assertTrue(response.metadata["handled_locally"])
        self.assertEqual(response.metadata["skill_used"], "html-boilerplate")

    def test_default_still_calls_provider(self):
        from app.api import orchestrator
        from app.core.providers.registry import ProviderDispatchResult
        dispatch = ProviderDispatchResult(
            result={"text": "x"}, metadata={"provider": "openai", "fallback_used": False}
        )
        mock = AsyncMock(return_value=dispatch)
        with patch.object(orchestrator.provider_registry, "generate_for_role", new=mock):
            asyncio.run(
                orchestrator.procesar_orquestacion("html", "hud_local", force_mode="ares")
            )
        mock.assert_awaited()


if __name__ == "__main__":
    unittest.main()
