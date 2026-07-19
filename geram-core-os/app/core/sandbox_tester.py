"""Deterministic, local adversarial checks for the closed Sandbox Guard catalog."""
import tempfile
from dataclasses import dataclass
from pathlib import Path
from app.core.sandbox_guard import ExecutionSpec, authorize, SANDBOX_POLICY_VERSION
from app.api import terminal_watcher
from app.core.sandbox_backend import detect_sandbox_backend, build_sandbox_prefix

PROFILES = {"standard"}
FIXTURES = ("stdout", "stderr", "failure", "timeout", "cancelable", "large_output", "environment_probe", "stdin_probe", "secret_output_probe", "child_tree", "child_tree_resistant", "fs_read_allowed", "fs_read_external", "fs_write_allowed", "fs_write_external")

@dataclass(frozen=True)
class Finding:
    test_id: str
    property: str
    classification: str
    evidence: str
    policy_version: int
    run_id: str | None = None
    decision_id: str | None = None
    limitation: str | None = None
    guard_allowed: bool = False
    process_started: bool = False
    operation_attempted: bool = False
    effect_observed: bool = False
    duration_ms: int | None = None

def classify(*, guard_allowed: bool, process_started: bool, attempted: bool,
             effect: bool, barrier: bool = False, capability: bool = True) -> str:
    """Classify evidence without treating fixture messages as proof."""
    if not capability:
        return "not_tested"
    if not guard_allowed and not process_started:
        return "policy_blocked"
    if process_started and attempted and barrier and not effect:
        return "runtime_prevented"
    if process_started and attempted and effect:
        return "runtime_allowed"
    return "inconclusive"

async def run_profile(profile: str = "standard") -> tuple[Finding, ...]:
    if profile not in PROFILES:
        raise ValueError("Sandbox Tester profile not allowed.")
    findings: list[Finding] = []
    with tempfile.TemporaryDirectory(prefix="geram-sandbox-tester-") as root:
        workspace = Path(root) / "workspace"; external = Path(root) / "external"
        workspace.mkdir(); external.mkdir()
        (workspace / "allowed.txt").write_text("synthetic-allowed", encoding="utf-8")
        (workspace / "allowed-write.txt").write_text("before", encoding="utf-8")
        (external / "external.txt").write_text("synthetic-external", encoding="utf-8")
        (external / "external-write-target").write_text("before", encoding="utf-8")
        old_root = terminal_watcher.settings.WORKSPACE_ROOT
        terminal_watcher.settings.WORKSPACE_ROOT = str(workspace)
        backend = detect_sandbox_backend()
        try:
            for fixture in FIXTURES:
                limit = .1 if fixture == "timeout" else (.2 if fixture in {"child_tree", "child_tree_resistant"} else 5)
                decision = authorize(ExecutionSpec(fixture, "synthetic_python_module", timeout_seconds=limit))
                if not decision.allowed or decision.spec is None:
                    findings.append(Finding(fixture, "authorization", "policy_blocked", "fixture rejected", SANDBOX_POLICY_VERSION, limitation="closed catalog")); continue
                run = terminal_watcher.Run(f"tester-{fixture}", fixture, list(decision.spec.args), ".", decision_id=decision.decision_id, policy_version=decision.policy_version, sandbox_prefix=build_sandbox_prefix(backend, workspace, Path(root)), sandbox_env={"PATH":"/usr/bin:/bin", "PYTHONUNBUFFERED":"1", "PYTHONPATH":"/opt/geram", "HOME":"/tmp/home"})
                await terminal_watcher._capture(run, decision.spec.timeout_seconds)
                classification = classify(guard_allowed=True, process_started=True, attempted=True, effect=run.status in {"succeeded", "failed", "timed_out", "cancelled"})
                evidence = run.status
                if run.truncated: evidence += "; truncated"
                findings.append(Finding(fixture, "process_observation", classification, evidence, decision.policy_version, run.run_id, decision.decision_id, "Standard mode does not provide kernel-level isolation.", True, True, True, run.status in {"succeeded", "failed", "timed_out", "cancelled"}, 0))
            findings.extend((
                Finding("filesystem", "filesystem_isolation", "not_tested", "additional isolation required", SANDBOX_POLICY_VERSION, limitation="the guard validates specifications but does not confine syscalls"),
                Finding("network", "network_isolation", "not_tested", "network namespace not enabled", SANDBOX_POLICY_VERSION, limitation="deny is a catalog policy, not kernel-level enforcement"),
                Finding("unregistered", "policy_boundary", "policy_blocked", "unregistered fixture; no process spawned", SANDBOX_POLICY_VERSION, limitation="catalog rejection does not prove runtime isolation"),
            ))
        finally:
            terminal_watcher.settings.WORKSPACE_ROOT = old_root
    return tuple(findings)
