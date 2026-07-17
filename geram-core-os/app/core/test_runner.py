"""Internal, allowlisted Python file and unittest runner."""
import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from app.api import terminal_watcher
from app.core.config import settings
from app.core.sandbox_backend import detect_sandbox_backend, build_sandbox_prefix, SandboxUnavailableError
from app.core.sandbox_guard import authorize_node_script, authorize_python_file, authorize_unittest

@dataclass(frozen=True)
class TestRunSpec:
    runner: str
    target: str
    timeout_seconds: float = 30.0
    selector: str = ""

_RUNNER_AUTHORIZERS = {
    "node_script": authorize_node_script,
    "python_file": authorize_python_file,
    "python_unittest": authorize_unittest,
}
_RUNNER_SUFFIXES = {
    "node_script": ".js",
    "python_file": ".py",
    "python_unittest": ".py",
}
_SANDBOX_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "PYTHONUNBUFFERED": "1",
    "PYTHONPATH": "/opt/geram",
    "HOME": "/tmp/home",
}


def _prepare_run(spec: TestRunSpec) -> tuple[terminal_watcher.Run, str] | dict:
    authorizer = _RUNNER_AUTHORIZERS.get(spec.runner)
    if authorizer is None:
        return {"status": "rejected", "error": "runner_not_allowed", "cleanup_status": "not_started"}
    root = Path(settings.WORKSPACE_ROOT).resolve()
    target = Path(spec.target)
    if target.is_absolute() or ".." in target.parts or target.suffix != _RUNNER_SUFFIXES[spec.runner]: return {"status": "rejected", "error": "target_not_allowed", "cleanup_status": "not_started"}
    target_path = (root / target).resolve()
    if root not in target_path.parents or not target_path.is_file(): return {"status": "rejected", "error": "target_not_allowed", "cleanup_status": "not_started"}
    decision = authorizer(target.as_posix(), spec.timeout_seconds, spec.selector) if spec.runner == "python_unittest" else authorizer(target.as_posix(), spec.timeout_seconds)
    if not decision.allowed or decision.spec is None:
        return {"status": "rejected", "error": decision.reason_code, "cleanup_status": "not_started"}
    try:
        backend = detect_sandbox_backend()
        prefix = build_sandbox_prefix(backend, root, root)
    except SandboxUnavailableError:
        return {"status": "unavailable", "error": "sandbox_unavailable", "cleanup_status": "not_started"}
    run = terminal_watcher.Run(
        uuid.uuid4().hex,
        spec.runner,
        list(decision.spec.args),
        ".",
        decision_id=decision.decision_id,
        policy_version=decision.policy_version,
        sandbox_prefix=prefix,
        sandbox_env=_SANDBOX_ENVIRONMENT.copy(),
        sandbox_backend=backend.name,
    )
    return run, backend.name


def start_test(spec: TestRunSpec) -> dict:
    prepared = _prepare_run(spec)
    if isinstance(prepared, dict):
        return prepared
    run, backend_name = prepared
    try:
        result = terminal_watcher.start_capture(run, spec.timeout_seconds)
    except RuntimeError as error:
        if str(error) == "run_capacity":
            return {"status": "rejected", "error": "run_capacity", "cleanup_status": "not_started"}
        raise
    result.update({"runner": spec.runner, "target": spec.target, "selector": spec.selector, "sandbox_backend": backend_name})
    return result


async def run_test(spec: TestRunSpec) -> dict:
    prepared = _prepare_run(spec)
    if isinstance(prepared, dict):
        return prepared
    run, backend_name = prepared
    await terminal_watcher._capture(run, spec.timeout_seconds)
    return {"status": run.status, "runner": spec.runner, "target": spec.target, "selector": spec.selector, "argv": terminal_watcher._safe_argv(run.argv), "exit_code": run.returncode, "stdout": run.stdout, "stderr": run.stderr, "duration_seconds": (run.finished-run.started) if run.finished and run.started else None, "termination_reason": run.termination_reason, "sandbox_backend": backend_name, "cleanup_status": run.cleanup_status}


async def run_unittest(spec: TestRunSpec) -> dict:
    """Compatibility wrapper retained for existing internal callers."""
    return await run_test(spec)
