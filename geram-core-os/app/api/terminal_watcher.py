"""Bounded observation of repository-controlled synthetic processes."""
import asyncio
import math
import os
import re
import signal
import sys
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.sandbox_backend import is_enforced_sandbox_prefix
from app.core.sandbox_guard import ExecutionSpec, authorize, environment, trusted_node_executable
from app.core.security import require_local_origin

router = APIRouter(prefix="/api/terminal-watcher", tags=["terminal-watcher"])
MAX_RUNS = 16
MAX_OUTPUT = 64 * 1024
DEFAULT_TIMEOUT = 5.0
MAX_TIMEOUT = 30.0
_TEST_RUNNER_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "PYTHONUNBUFFERED": "1",
    "PYTHONPATH": "/opt/geram",
    "HOME": "/tmp/home",
}
_ANSI_SEQUENCE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token)(\s*[:=]\s*)([^\s,;]+)"
)

CATALOG = {name for name in ("stdout", "stderr", "failure", "timeout", "cancelable", "large_output", "child_tree", "child_tree_resistant", "fs_read_allowed", "fs_read_external", "fs_write_allowed", "fs_write_external")}

class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=1, max_length=32)
    timeout_seconds: float | None = Field(default=None, gt=0, le=MAX_TIMEOUT)

@dataclass
class Run:
    run_id: str
    task: str
    argv: list[str]
    cwd: str
    started: float | None = None
    finished: float | None = None
    status: str = "queued"
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    truncated: bool = False
    error: str | None = None
    decision_id: str | None = None
    policy_version: int | None = None
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    sandbox_prefix: list[str] = field(default_factory=list, repr=False)
    sandbox_env: dict[str, str] | None = field(default=None, repr=False)
    leader_pid: int | None = None
    process_group_id: int | None = None
    session_id: int | None = None
    known_descendant_pids: list[int] = field(default_factory=list)
    signals_sent: list[str] = field(default_factory=list)
    escalated: bool = False
    termination_reason: str | None = None
    cleanup_status: str = "pending"
    sandbox_backend: str | None = None

    def public(self) -> dict[str, Any]:
        duration = None if self.started is None else (self.finished or time.monotonic()) - self.started
        return {"run_id": self.run_id, "purpose": self.task, "decision_id": self.decision_id, "policy_version": self.policy_version, "argv": _safe_argv(self.argv),
                "cwd": self.cwd, "status": self.status, "started_at": self.started,
                "finished_at": self.finished, "duration_seconds": duration,
                "stdout": self.stdout, "stderr": self.stderr, "returncode": self.returncode,
                "truncated": self.truncated, "stdout_bytes": self.stdout_bytes,
                "stderr_bytes": self.stderr_bytes, "error": self.error,
                "leader_pid": self.leader_pid, "process_group_id": self.process_group_id,
                "session_id": self.session_id, "known_descendant_pids": list(self.known_descendant_pids),
                "signals_sent": list(self.signals_sent), "escalated": self.escalated,
                "termination_reason": self.termination_reason, "cleanup_status": self.cleanup_status,
                "sandbox_backend": self.sandbox_backend}

_runs: dict[str, Run] = {}
_tasks: dict[str, asyncio.Task] = {}

def _safe_argv(argv: list[str]) -> list[str]:
    result = []
    redact = False
    for value in argv:
        if redact:
            result.append("[REDACTED]"); redact = False; continue
        if value.lower().lstrip("-").replace("_", "-") in {"token", "api-key", "password", "secret", "authorization"}:
            result.append(value); redact = True
        else:
            result.append(value if not Path(value).is_absolute() else "[PATH]")
    return result


def _bounded_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8", "replace")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", "ignore")


def _sanitize_output(raw: bytes, truncated: bool) -> str:
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    text = _ANSI_SEQUENCE.sub("", text)
    text = "".join(
        character
        if character in {"\n", "\t"} or unicodedata.category(character) not in {"Cc", "Cf"}
        else "�"
        for character in text
    )
    text = _SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", text)
    marker = "\n[output truncated]\n" if truncated else ""
    if marker:
        text = _bounded_utf8(text, MAX_OUTPUT - len(marker.encode("utf-8"))) + marker
    return _bounded_utf8(text, MAX_OUTPUT)


def _execution_argv(run: Run) -> list[str]:
    sandboxed = bool(run.sandbox_prefix)
    if run.task == "python_unittest":
        if run.cwd != "." or run.sandbox_env != _TEST_RUNNER_ENVIRONMENT:
            raise RuntimeError("Closed test runner profile is invalid.")
        whole_file = len(run.argv) == 4 and run.argv[:3] == ["/usr/bin/python3", "-m", "unittest"]
        selected = (
            len(run.argv) == 6
            and run.argv[:4] == ["/usr/bin/python3", "-m", "unittest", "-k"]
            and re.fullmatch(r"[A-Za-z_]\w{0,127}(?:\.test_[A-Za-z0-9_]{1,120})?", run.argv[4]) is not None
            and re.fullmatch(r"(?!-)(?!.*(?:^|/)\.\.?/)[^\x00\r\n]+\.py", run.argv[5]) is not None
        )
        if not whole_file and not selected:
            raise RuntimeError("Closed test runner argv is invalid.")
        sandboxed = True
    elif run.task == "python_file":
        if run.cwd != "." or run.sandbox_env != _TEST_RUNNER_ENVIRONMENT:
            raise RuntimeError("Closed Python runner profile is invalid.")
        if len(run.argv) != 2 or run.argv[0] != "/usr/bin/python3":
            raise RuntimeError("Closed Python runner argv is invalid.")
        sandboxed = True
    elif run.task == "node_script":
        node = trusted_node_executable()
        if run.cwd != "." or run.sandbox_env != _TEST_RUNNER_ENVIRONMENT:
            raise RuntimeError("Closed Node runner profile is invalid.")
        if node is None or len(run.argv) != 3 or run.argv[:2] != [str(node), "--"]:
            raise RuntimeError("Closed Node runner argv is invalid.")
        sandboxed = True
    if sandboxed and not is_enforced_sandbox_prefix(run.sandbox_prefix):
        raise RuntimeError("An enforced sandbox prefix is required.")
    return run.sandbox_prefix + run.argv

def _workspace() -> Path:
    return Path(settings.WORKSPACE_ROOT).resolve()

async def _capture(run: Run, timeout: float) -> None:
    capture_started = time.monotonic()
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    try:
        if run.status == "cancelled":
            run.finished = time.monotonic()
            run.cleanup_status = "clean"
            return
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise RuntimeError("Invalid closed task timeout.")
        deadline = time.monotonic() + timeout
        env = run.sandbox_env or environment()
        run.process = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *_execution_argv(run),
                cwd=_workspace(),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            ),
            max(0.001, deadline - time.monotonic()),
        )
        run.started = capture_started
        run.leader_pid = run.process.pid
        try:
            run.process_group_id = os.getpgid(run.process.pid)
            run.session_id = os.getsid(run.process.pid)
        except ProcessLookupError:
            run.process_group_id = run.process.pid
            run.session_id = run.process.pid
        run.known_descendant_pids = _descendants(run.leader_pid)
        if run.status == "cancelled":
            raise asyncio.CancelledError
        run.status = "running"
        async def read(stream: asyncio.StreamReader, which: str, buffer: bytearray):
            while True:
                chunk = await stream.read(4096)
                if not chunk: break
                if which == "stdout": run.stdout_bytes += len(chunk)
                else: run.stderr_bytes += len(chunk)
                remaining = MAX_OUTPUT - len(buffer)
                if remaining > 0:
                    buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    run.truncated = True
        await asyncio.wait_for(
            asyncio.gather(
                read(run.process.stdout, "stdout", stdout_buffer),
                read(run.process.stderr, "stderr", stderr_buffer),
                run.process.wait(),
            ),
            max(0.001, deadline - time.monotonic()),
        )
        run.returncode = run.process.returncode
        run.status = "succeeded" if run.returncode == 0 else "failed"
        if run.returncode:
            run.termination_reason = "exit_nonzero"
    except asyncio.TimeoutError:
        run.status = "timed_out"
        run.termination_reason = "timeout"
        if run.process and run.process.returncode is None:
            await _terminate_group(run)
    except asyncio.CancelledError:
        run.status = "cancelled"
        run.termination_reason = "cancelled"
        if run.process and run.process.returncode is None:
            await _terminate_group(run)
        raise
    except Exception:
        run.status = "spawn_error"
        run.termination_reason = "spawn_error"
        run.error = "The controlled task could not be started."
    finally:
        if run.process and run.process.returncode is None:
            if run.process_group_id is None and run.leader_pid:
                run.process_group_id = run.leader_pid
            await _terminate_group(run)
        stdout_truncated = run.stdout_bytes > len(stdout_buffer)
        stderr_truncated = run.stderr_bytes > len(stderr_buffer)
        run.stdout = _sanitize_output(bytes(stdout_buffer), stdout_truncated)
        run.stderr = _sanitize_output(bytes(stderr_buffer), stderr_truncated)
        run.truncated = run.truncated or stdout_truncated or stderr_truncated
        run.finished = time.monotonic()
        if run.leader_pid is None:
            run.cleanup_status = "clean" if run.status == "cancelled" else "not_started"
        else:
            run.cleanup_status = "clean" if not _known_alive(run) else "residual"
        if run.cleanup_status == "residual":
            run.termination_reason = "cleanup_failed"
        run.process = None


def start_capture(run: Run, timeout: float) -> dict[str, Any]:
    """Register one already-authorized closed run for polling/cancellation."""
    if sum(item.status in {"queued", "running"} for item in _runs.values()) >= 1:
        raise RuntimeError("run_capacity")
    _runs[run.run_id] = run
    while len(_runs) > MAX_RUNS:
        _runs.pop(next(iter(_runs)))
    _tasks[run.run_id] = asyncio.create_task(_capture(run, timeout))
    return run.public()

def _descendants(pid: int) -> list[int]:
    """Inspect descendants of a known leader without name-based matching."""
    if not Path("/proc").is_dir(): return []
    parents = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit(): continue
        try:
            stat = (entry / "stat").read_text(encoding="ascii")
            fields = stat[stat.rfind(")") + 2:].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, ValueError, IndexError): continue
    result, pending = [], [pid]
    while pending:
        parent = pending.pop()
        children = [child for child, ppid in parents.items() if ppid == parent]
        result.extend(children); pending.extend(children)
    return sorted(set(result))

def _known_alive(run: Run) -> bool:
    if not Path("/proc").is_dir(): return False
    return any(Path("/proc", str(pid)).exists() for pid in [run.leader_pid, *run.known_descendant_pids] if pid)

async def _terminate_group(run: Run) -> None:
    if not run.process_group_id: run.cleanup_status = "not_tested"; return
    if run.leader_pid:
        run.known_descendant_pids = sorted(set(run.known_descendant_pids + _descendants(run.leader_pid)))
    known = [pid for pid in [run.leader_pid, *run.known_descendant_pids] if pid]

    def signal_known(selected_signal: signal.Signals) -> bool:
        sent = False
        group_owned = False
        for pid in known:
            try:
                if os.getpgid(pid) == run.process_group_id:
                    group_owned = True
                    break
            except ProcessLookupError:
                continue
        if group_owned:
            try:
                os.killpg(run.process_group_id, selected_signal)
                sent = True
            except ProcessLookupError:
                pass
        for pid in run.known_descendant_pids:
            try:
                if os.getpgid(pid) != run.process_group_id:
                    os.kill(pid, selected_signal)
                    sent = True
            except ProcessLookupError:
                continue
        if sent:
            run.signals_sent.append(selected_signal.name)
        return sent

    signal_known(signal.SIGTERM)
    await asyncio.sleep(0.05)
    if _known_alive(run):
        run.escalated = signal_known(signal.SIGKILL)
    if run.process:
        try:
            await asyncio.wait_for(run.process.wait(), 1.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            pass
    deadline = time.monotonic() + 1.0
    while _known_alive(run) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)

@router.post("/runs")
async def start_run(request: Request, body: StartRequest):
    require_local_origin(request)
    if body.task not in CATALOG: raise HTTPException(422, "Task not allowed.")
    decision = authorize(ExecutionSpec(body.task, "synthetic_python_module", timeout_seconds=body.timeout_seconds or DEFAULT_TIMEOUT))
    if not decision.allowed or decision.spec is None: raise HTTPException(422, decision.message)
    task = body.task
    run = Run(uuid.uuid4().hex, task, list(decision.spec.args), decision.spec.cwd)
    run.decision_id = decision.decision_id
    run.policy_version = decision.policy_version
    try:
        return start_capture(run, body.timeout_seconds or DEFAULT_TIMEOUT)
    except RuntimeError as error:
        if str(error) == "run_capacity":
            raise HTTPException(409, "A task is already running.") from None
        raise

@router.get("/runs")
async def list_runs(): return {"runs": [r.public() for r in _runs.values()]}

@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = _runs.get(run_id)
    if not run: raise HTTPException(404, "Run not found.")
    return run.public()

@router.post("/runs/{run_id}/cancel")
async def cancel_run(request: Request, run_id: str):
    require_local_origin(request)
    run = _runs.get(run_id)
    if not run: raise HTTPException(404, "Run not found.")
    if run.status not in {"queued", "running"}: raise HTTPException(409, "The run has already finished.")
    task = _tasks.get(run_id)
    if task:
        run.status = "cancelled"
        run.termination_reason = "cancelled"
        if run.process is None:
            # Let an in-flight create_subprocess call finish so _capture owns
            # the process handle and can terminate it deterministically.
            # Cancelling that await can orphan the transport before assignment.
            run.cleanup_status = "pending"
        else:
            task.cancel()
    return run.public()
