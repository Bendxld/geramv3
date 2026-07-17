#!/usr/bin/env python3
"""Offline, synthetic terminal demo of the two approved A.R.E.S. workflows."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.test_ares_server_smoke import (
    AresRealServerSmokeTests,
    BASE_CONTENT,
    DETACHED_MARKER,
    PROPOSED_CONTENT,
    ROOT,
    SmokeServer,
    _pids_with_cmdline_marker,
)


def show(number: int, title: str, detail: str) -> None:
    print(f"\n[{number}/11] {title}\n{detail}")


def detail_code(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


def run_demo() -> None:
    workspace_path: Path
    data_path: Path
    log_path: Path
    driver = AresRealServerSmokeTests("test_real_server_edit_and_runner_workflows")

    with (
        tempfile.TemporaryDirectory(prefix=".ares-demo-workspace-", dir=ROOT) as workspace_name,
        tempfile.TemporaryDirectory(prefix=".ares-demo-data-", dir=ROOT.parent) as data_name,
        # Settings normalizes relative log paths with lstrip("./"), so this
        # managed name must not begin with a dot or cleanup would miss a sibling.
        tempfile.TemporaryDirectory(prefix="ares-demo-logs-", dir=ROOT) as log_name,
    ):
        workspace_path = Path(workspace_name)
        data_path = Path(data_name)
        log_path = Path(log_name)
        (workspace_path / "smoke_edit.py").write_text(BASE_CONTENT, encoding="utf-8")
        (workspace_path / ".env.py").write_text("SYNTHETIC_ONLY = True\n", encoding="utf-8")
        driver.workspace = workspace_path

        with SmokeServer(workspace_path, data_path, log_path) as server:
            client = server.client
            health = client.json("GET", "/health")
            assert health.get("status") == "ok"
            show(1, "Servidor y health check", "GET /health -> status=ok; bind=127.0.0.1")

            proposal = driver._propose(client)
            assert proposal["state"] == "proposed"
            assert driver._read_edit(client)["content"] == BASE_CONTENT
            show(2, "Propuesta sintética", "state=proposed; smoke_edit.py todavía no cambió")
            show(3, "Diff revisable antes de escribir", proposal["diff"].rstrip())

            no_approval_status, no_approval, _raw = client.request(
                "POST",
                "/api/ares/proposals/apply",
                {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                    "approval_token": "A" * 43,
                },
                origin=client.local_origin,
            )
            assert no_approval_status == 409
            assert detail_code(no_approval) == "proposal_not_approved"
            show(4, "Apply sin aprobación", "409 proposal_not_approved; archivo intacto")

            approval = driver._approve(client, proposal)
            assert approval["state"] == "approved"
            assert driver._read_edit(client)["content"] == BASE_CONTENT
            show(5, "Aprobación separada", "state=approved; archivo todavía intacto; token no mostrado")

            applied = client.json(
                "POST",
                "/api/ares/proposals/apply",
                driver._apply_payload(proposal, approval),
                origin=client.local_origin,
            )
            assert applied["state"] == "applied"
            assert driver._read_edit(client)["content"] == PROPOSED_CONTENT
            show(6, "Aplicación controlada", "state=applied; contenido sintético aplicado")
            driver._restore_base(client)

            conflicted = driver._propose(client)
            conflicted_approval = driver._approve(client, conflicted)
            current = driver._read_edit(client)
            client.json(
                "PUT",
                "/api/workspace/file",
                {
                    "path": "smoke_edit.py",
                    "content": "VALUE = 'conflict'\n",
                    "base_version": current["version"],
                },
                origin=client.local_origin,
            )
            conflict_status, conflict, _raw = client.request(
                "POST",
                "/api/ares/proposals/apply",
                driver._apply_payload(conflicted, conflicted_approval),
                origin=client.local_origin,
            )
            assert conflict_status == 409
            assert detail_code(conflict) == "version_conflict"
            assert driver._read_edit(client)["content"] == "VALUE = 'conflict'\n"
            show(7, "Conflicto de versión", "409 version_conflict; contenido local preservado")
            driver._restore_base(client)

            driver._write_runner_test(server.port)
            runner = client.json(
                "POST",
                "/api/ares/tests",
                {
                    "runner": "python_unittest",
                    "target": "test_smoke_runner.py",
                    "timeout_seconds": 5.0,
                },
                origin=client.local_origin,
            )
            assert runner["status"] == "succeeded"
            assert runner["sandbox_backend"] == "bubblewrap"
            assert runner["cleanup_status"] == "clean"
            assert "network-blocked" in runner["stdout"]
            assert not _pids_with_cmdline_marker(DETACHED_MARKER)
            show(8, "Unittest aislado", "succeeded; bubblewrap; network-blocked; cleanup=clean")

            invalid = client.json(
                "POST",
                "/api/ares/tests",
                {"runner": "python_unittest", "target": ".env.py"},
                origin=client.local_origin,
            )
            assert invalid["status"] == "rejected"
            assert invalid["cleanup_status"] == "not_started"
            show(9, "Target sensible", "rejected; cleanup=not_started")

            assert driver._read_edit(client)["content"] == BASE_CONTENT

        with SmokeServer(
            workspace_path,
            data_path,
            log_path,
            disable_bwrap=True,
        ) as unavailable_server:
            driver._write_runner_test(unavailable_server.port)
            unavailable = unavailable_server.client.json(
                "POST",
                "/api/ares/tests",
                {
                    "runner": "python_unittest",
                    "target": "test_smoke_runner.py",
                    "timeout_seconds": 5.0,
                },
                origin=unavailable_server.client.local_origin,
            )
            assert unavailable == {
                "status": "unavailable",
                "error": "sandbox_unavailable",
                "cleanup_status": "not_started",
            }
            show(10, "Bubblewrap no disponible", "sandbox_unavailable; cleanup=not_started; sin spawn")

        assert (workspace_path / "smoke_edit.py").read_text(encoding="utf-8") == BASE_CONTENT
        assert not _pids_with_cmdline_marker(DETACHED_MARKER)

    assert not workspace_path.exists()
    assert not data_path.exists()
    assert not log_path.exists()
    show(11, "Limpieza", "archivo base restaurado; temporales y procesos sintéticos eliminados")


if __name__ == "__main__":
    run_demo()
