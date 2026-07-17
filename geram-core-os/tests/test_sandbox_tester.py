import unittest
from app.core.sandbox_tester import run_profile, classify

class SandboxTesterTests(unittest.IsolatedAsyncioTestCase):
    async def test_standard_profile_is_closed_and_sanitized(self):
        findings = await run_profile()
        self.assertEqual(len(findings), 18)
        self.assertTrue(all(f.policy_version == 1 for f in findings))
        self.assertTrue(all('/' not in f.evidence for f in findings))
        self.assertIn("runtime_allowed", {f.classification for f in findings})
        self.assertIn("not_tested", {f.classification for f in findings})
        self.assertIn("policy_blocked", {f.classification for f in findings})
    async def test_unknown_profile_rejected(self):
        with self.assertRaises(ValueError): await run_profile('network-isolated')

    async def test_filesystem_and_process_findings_are_externalized(self):
        findings = await run_profile()
        by_id = {item.test_id: item for item in findings}
        self.assertEqual(by_id["fs_read_allowed"].classification, "runtime_allowed")
        self.assertEqual(by_id["fs_read_external"].classification, "runtime_allowed")
        self.assertTrue(by_id["child_tree"].run_id)

    def test_classification_does_not_trust_fixture_text(self):
        self.assertEqual(classify(guard_allowed=False, process_started=False, attempted=False, effect=False), "policy_blocked")
        self.assertEqual(classify(guard_allowed=True, process_started=True, attempted=True, effect=False, barrier=True), "runtime_prevented")
        self.assertEqual(classify(guard_allowed=True, process_started=True, attempted=True, effect=True), "runtime_allowed")
        self.assertEqual(classify(guard_allowed=True, process_started=False, attempted=False, effect=False, capability=False), "not_tested")
        self.assertEqual(classify(guard_allowed=True, process_started=True, attempted=False, effect=False), "inconclusive")
