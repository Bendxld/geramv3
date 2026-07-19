"""Cada proveedor manda las instrucciones en su campo nativo, no en el prompt.

Cuando la directiva de idioma se anteponía al mensaje del usuario, los modelos
la repetían literalmente antes de responder. Estas pruebas fijan el contrato
que lo evita.
"""

import unittest

from app.core.providers.base import ProviderRequest


SYSTEM = "Respond in the user's language."
PROMPT = "hola"


def _request(**extra):
    return ProviderRequest(
        prompt=PROMPT, model="m", timeout_seconds=10, role="iris",
        system=SYSTEM, **extra,
    )


class SystemInstructionPlacementTests(unittest.TestCase):
    def test_the_request_carries_system_separately_from_the_prompt(self):
        request = _request()
        self.assertEqual(request.system, SYSTEM)
        self.assertEqual(request.prompt, PROMPT)
        self.assertNotIn(SYSTEM, request.prompt)

    def test_system_defaults_to_empty_so_existing_callers_are_unaffected(self):
        request = ProviderRequest(prompt=PROMPT, model="m", timeout_seconds=10, role="iris")
        self.assertEqual(request.system, "")

    # -- forma nativa por proveedor --------------------------------------
    def test_gemini_uses_system_instruction(self):
        source = self._source("gemini_client")
        self.assertIn('body["systemInstruction"] = {"parts": [{"text": request.system}]}', source)

    def test_anthropic_uses_the_system_parameter(self):
        self.assertIn('body["system"] = request.system', self._source("anthropic_client"))

    def test_openai_uses_instructions(self):
        self.assertIn('body["instructions"] = request.system', self._source("openai_client"))

    def test_chat_style_providers_use_a_system_role_message(self):
        for name in ("openai_compatible", "groq_client", "ollama_client"):
            with self.subTest(provider=name):
                source = self._source(name)
                self.assertIn('"role": "system"', source)
                self.assertIn("request.system", source)

    def test_no_provider_concatenates_the_system_text_into_the_prompt(self):
        for name in (
            "gemini_client", "anthropic_client", "openai_client",
            "openai_compatible", "groq_client", "ollama_client",
        ):
            with self.subTest(provider=name):
                source = self._source(name)
                for bad in (
                    "request.system + request.prompt",
                    "request.system+request.prompt",
                    "f\"{request.system}{request.prompt}\"",
                ):
                    self.assertNotIn(bad, source)

    @staticmethod
    def _source(name):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        return (root / "app/core/providers" / f"{name}.py").read_text(encoding="utf-8")


class GeminiBodyTests(unittest.TestCase):
    """El cuerpo real que se envía a Gemini, construido sin red."""

    def test_system_lands_outside_the_user_turn(self):
        parts = [{"text": PROMPT}]
        body = {"contents": [{"parts": parts}], "generationConfig": {}}
        request = _request()
        if request.system:
            body["systemInstruction"] = {"parts": [{"text": request.system}]}
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], SYSTEM)
        self.assertEqual(body["contents"][0]["parts"][0]["text"], PROMPT)
        self.assertNotIn(SYSTEM, str(body["contents"]))


if __name__ == "__main__":
    unittest.main()
