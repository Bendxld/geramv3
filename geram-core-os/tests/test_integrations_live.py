"""Opt-in, read-only contract tests against user-provided integration accounts.

Run only with GERAM_LIVE_INTEGRATION_TESTS=1. The normal suite skips this file
and no secret value is ever printed or included in an assertion message.
"""

import json
import os
import unittest

from app.core.config import settings
from app.core.gcs.integrations import integration_hub


@unittest.skipUnless(
    os.environ.get("GERAM_LIVE_INTEGRATION_TESTS") == "1",
    "live integration credentials were not explicitly enabled",
)
class LiveIntegrationContractTests(unittest.TestCase):
    def test_all_configured_integrations_support_a_read_only_call(self):
        table = os.environ.get("GERAM_LIVE_SUPABASE_TABLE", "").strip()
        calls = {
            "spotify": ("status", {}),
            "notion": ("status", {}),
            "telegram": ("status", {}),
            "supabase": ("select", {"table": table, "limit": 1}),
            "google-calendar": ("list_events", {"max_results": 1}),
            "obsidian": ("list_notes", {"limit": 1}),
        }
        self.assertTrue(table, "GERAM_LIVE_SUPABASE_TABLE is required for opt-in live tests")
        secret_values = [
            settings.SPOTIFY_ACCESS_TOKEN,
            settings.NOTION_API_KEY,
            settings.TELEGRAM_BOT_TOKEN,
            settings.SUPABASE_KEY,
            settings.GOOGLE_CALENDAR_ACCESS_TOKEN,
        ]
        for integration_id, (action, params) in calls.items():
            with self.subTest(integration=integration_id):
                adapter = integration_hub.get(integration_id)
                self.assertIsNotNone(adapter)
                self.assertTrue(adapter.is_connected())
                result = integration_hub.invoke(
                    integration_id,
                    action,
                    params,
                    granted=[adapter.permission.value],
                    approved=False,
                )
                self.assertEqual(result.status, "ok")
                rendered = json.dumps(result.as_dict(), sort_keys=True)
                for secret in secret_values:
                    if secret:
                        self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
