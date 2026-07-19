"""Portable per-user state, media, roster, and multimodal routing tests."""

from __future__ import annotations

import asyncio
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.api import orchestrator
from app.core.agent_roster import AgentRosterError, AgentRosterStore
from app.core.attachments import (
    AttachmentError,
    AttachmentStore,
    ConsumedAttachment,
)
from app.core.config import settings
from app.core.providers.base import ProviderAttachment
from app.core.providers.registry import ProviderDispatchResult
from app.core.runtime_state import RuntimePreferences, RuntimeStateStore
from app.websocket.hud_socket import MAX_HUD_MESSAGE_BYTES, handle_hud_message
from app.core.agent_loader import AgentRegistry


class RuntimeStateTests(unittest.TestCase):
    def test_state_is_per_user_owner_only_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "LOCAL_DATA_DIR", Path(directory)
        ):
            store = RuntimeStateStore()
            self.assertTrue(store.load().voice_enabled)
            store.update({"voice_enabled": False, "offline_forced": True})
            loaded = RuntimeStateStore().load()
            self.assertFalse(loaded.voice_enabled)
            self.assertTrue(loaded.offline_forced)
            self.assertEqual(stat.S_IMODE(os.stat(store.path()).st_mode), 0o600)


class HudMessageTests(unittest.IsolatedAsyncioTestCase):
    class Socket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    async def test_hud_controls_are_bounded_and_use_runtime_store(self):
        socket = self.Socket()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "LOCAL_DATA_DIR", Path(directory)
        ):
            await handle_hud_message(
                socket,
                '{"type":"set_runtime_state","data":{"offline_forced":true}}',
            )
            self.assertEqual(socket.messages[-1]["type"], "runtime_state")
            self.assertTrue(socket.messages[-1]["data"]["offline_forced"])
            await handle_hud_message(socket, '{"type":"get_runtime_state"}')
            self.assertTrue(socket.messages[-1]["data"]["offline_forced"])

            await handle_hud_message(socket, "x" * (MAX_HUD_MESSAGE_BYTES + 1))
            self.assertEqual(socket.messages[-1]["error"]["code"], "message_too_large")
            await handle_hud_message(socket, '{"type":"run_shell","data":"rm"}')
            self.assertEqual(socket.messages[-1]["error"]["code"], "unsupported_message")


class AttachmentStoreTests(unittest.TestCase):
    PNG = b"\x89PNG\r\n\x1a\n" + b"unit-test-image"

    def test_image_roundtrip_is_bounded_and_one_shot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "LOCAL_DATA_DIR", Path(directory)
        ):
            store = AttachmentStore()
            saved = store.save("camera.png", self.PNG)
            self.assertEqual(saved, {"tipo": "image", "nombre": "camera.png"})
            consumed = store.consume()
            self.assertIsInstance(consumed.provider_attachment, ProviderAttachment)
            self.assertEqual(consumed.provider_attachment.data, self.PNG)
            self.assertIsNone(store.consume())

    def test_pdf_text_is_injected_as_untrusted_content(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "LOCAL_DATA_DIR", Path(directory)
        ):
            store = AttachmentStore()
            store.save("notes.pdf", b"%PDF-1.7\nunit-test")
            with patch.object(store, "_pdf_text", return_value="PDF body"):
                consumed = store.consume()
            self.assertIn("untrusted user content", consumed.prompt_context)
            self.assertIn("PDF body", consumed.prompt_context)

    def test_unknown_file_signature_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            settings, "LOCAL_DATA_DIR", Path(directory)
        ):
            with self.assertRaises(AttachmentError):
                AttachmentStore().save("fake.png", b"not really an image")


class AgentRosterTests(unittest.TestCase):
    def test_every_bundled_agent_is_discovered_without_importing_it(self):
        with tempfile.TemporaryDirectory() as agents_directory, tempfile.TemporaryDirectory() as data_directory:
            agents = Path(agents_directory)
            (agents / "director.py").write_text("raise RuntimeError('must not import')\n")
            (agents / "spotify_agent.py").write_text("raise RuntimeError('must not import')\n")
            with patch.object(settings, "AGENTS_DIR", agents), patch.object(
                settings, "LOCAL_DATA_DIR", Path(data_directory)
            ), patch("app.core.agent_roster.agent_factory.list_all", return_value=[]), patch(
                "app.core.agent_roster.agent_registry.list_loaded", return_value=[]
            ):
                store = AgentRosterStore()
                roster = {item["nombre"]: item for item in store.list_all()}
                self.assertEqual(set(roster), {"director", "spotify_agent"})
                self.assertTrue(roster["director"]["core"])
                updated = store.set_enabled("bundled:spotify_agent", False)
                self.assertFalse(updated["enabled"])
                self.assertFalse(
                    next(item for item in store.list_all() if item["nombre"] == "spotify_agent")["enabled"]
                )
                with self.assertRaises(AgentRosterError):
                    store.set_enabled("bundled:director", False)

    def test_disabling_a_loaded_agent_unloads_it_and_blocks_future_loads(self):
        with tempfile.TemporaryDirectory() as agents_directory, tempfile.TemporaryDirectory() as data_directory:
            agents = Path(agents_directory)
            (agents / "spotify_agent.py").write_text("VALUE = 1\n", encoding="utf-8")
            with patch.object(settings, "AGENTS_DIR", agents), patch.object(
                settings, "LOCAL_DATA_DIR", Path(data_directory)
            ), patch("app.core.agent_roster.agent_factory.list_all", return_value=[]), patch(
                "app.core.agent_roster.agent_registry.list_loaded",
                return_value=[{"name": "spotify_agent", "loaded_at": 1}],
            ), patch("app.core.agent_roster.agent_registry.unload") as unload:
                store = AgentRosterStore()
                store.set_enabled("bundled:spotify_agent", False)
                unload.assert_called_once_with("spotify_agent")
            registry = AgentRegistry()
            with patch("app.core.agent_roster.agent_roster_store.is_enabled", return_value=False):
                with self.assertRaises(PermissionError):
                    registry.load("spotify_agent")


class AttachmentRoutingTests(unittest.TestCase):
    def test_hud_attachment_reaches_the_selected_multimodal_provider(self):
        attachment = ProviderAttachment(
            media_type="image/png", data=AttachmentStoreTests.PNG, filename="x.png"
        )
        dispatch = ProviderDispatchResult(
            result={"text": "image understood"},
            metadata={"provider": "gemini", "model": "test", "fallback_used": False},
        )
        generate = AsyncMock(return_value=dispatch)
        with patch.object(
            orchestrator.attachment_store,
            "consume",
            return_value=ConsumedAttachment(provider_attachment=attachment),
        ), patch.object(
            orchestrator.runtime_state_store,
            "load",
            return_value=RuntimePreferences(),
        ), patch.object(
            orchestrator.provider_registry,
            "generate_for_role",
            new=generate,
        ):
            response = asyncio.run(orchestrator.procesar_orquestacion(
                "what is here?", "hud_local", use_pending_attachment=True
            ))
        self.assertEqual(response.result["text"], "image understood")
        self.assertEqual(generate.await_args.kwargs["attachments"], (attachment,))


if __name__ == "__main__":
    unittest.main()
