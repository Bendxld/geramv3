"""Security and correctness tests for the local workspace foundation."""

import asyncio
import json
import logging
import os
import stat
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import Response

from app.api import workspace as workspace_api
from app.core.config import (
    ROOT_DIR,
    Settings,
    SettingsValidationError,
    developer_mode_enabled,
    validate_workspace_root,
)
from app.core.security import require_local_origin, require_localhost
from app.core.workspace import (
    _DIR_FD_OK,
    TEMPORARY_PREFIX,
    WorkspaceError,
    WorkspaceService,
)
from app.middleware.session_logging import SessionLoggingMiddleware, logger


def _request(origin=None, host="127.0.0.1", method="PUT"):
    headers = []
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/workspace/file",
            "query_string": b"",
            "headers": headers,
            "client": (host, 41000),
            "server": ("127.0.0.1", 8000),
            "scheme": "http",
        }
    )


class WorkspaceSettingsTests(unittest.TestCase):
    def test_default_root_is_isolated_user_workspace_not_source(self):
        # SEGURIDAD (v3): el default NUNCA es el código fuente de GERAM, sino
        # un directorio de usuario aislado (~/geram-workspace). Así el
        # explorador/editor/A.R.E.S. no pueden ver ni editar los internos.
        with tempfile.TemporaryDirectory() as other_directory:
            previous = Path.cwd()
            try:
                os.chdir(other_directory)
                configured = Settings(environ={}, create_runtime_dirs=False)
            finally:
                os.chdir(previous)
        expected = (Path.home() / "geram-workspace").resolve()
        self.assertEqual(configured.WORKSPACE_ROOT, expected)
        self.assertNotEqual(configured.WORKSPACE_ROOT, ROOT_DIR.resolve())
        self.assertFalse(configured.WORKSPACE_ROOT.is_relative_to(ROOT_DIR.resolve()))

    def test_developer_mode_unlocks_the_source_root(self):
        # MODO DESARROLLADOR (v3): con el switch activo, el workspace pasa a ser
        # la raíz del código de GERAM para hackear los internos.
        safe = validate_workspace_root("", create_default=False, developer_mode=False)
        dev = validate_workspace_root("", create_default=False, developer_mode=True)
        self.assertEqual(dev, ROOT_DIR.resolve())
        self.assertNotEqual(dev, safe)

    def test_developer_mode_flag_is_read_from_config_json(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / ".geram-config.json"
            config_path.write_text(
                json.dumps({"privacy_controls": {"developer_mode": True}}),
                encoding="utf-8",
            )
            self.assertTrue(developer_mode_enabled(config_path))
        # Fail-safe: archivo ausente o inválido -> modo seguro (False).
        self.assertFalse(developer_mode_enabled(Path(directory) / "gone.json"))

    def test_explicit_existing_directory_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            configured = Settings(
                environ={"GERAM_WORKSPACE_ROOT": directory},
                create_runtime_dirs=False,
            )
        self.assertEqual(configured.WORKSPACE_ROOT, Path(directory).resolve())

    def test_missing_root_is_rejected_without_echoing_value(self):
        synthetic = "missing-workspace-unit-test"
        with self.assertRaises(SettingsValidationError) as raised:
            validate_workspace_root(synthetic)
        self.assertNotIn(synthetic, str(raised.exception))

    def test_home_and_system_root_are_rejected_as_too_broad(self):
        for candidate in (Path.home(), Path("/"), Path("/tmp")):
            with self.subTest(candidate=candidate.name or "root"):
                with self.assertRaises(SettingsValidationError) as raised:
                    validate_workspace_root(str(candidate))
                self.assertEqual(raised.exception.code, "unsafe_workspace_root")

    def test_public_static_tree_cannot_be_the_workspace_root(self):
        with self.assertRaises(SettingsValidationError) as raised:
            validate_workspace_root(str(ROOT_DIR / "static"))
        self.assertEqual(raised.exception.code, "unsafe_workspace_root")


class WorkspaceServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.container = Path(self.temporary.name)
        self.root = self.container / "workspace"
        self.root.mkdir()
        self.service = WorkspaceService(self.root)

    def write_bytes(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def write_text(self, relative, content, mode=0o644):
        path = self.write_bytes(relative, content.encode("utf-8"))
        path.chmod(mode)
        return path

    def assert_error(self, code, operation):
        with self.assertRaises(WorkspaceError) as raised:
            operation()
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn(str(self.root), str(raised.exception))
        return raised.exception


class WorkspacePathSecurityTests(WorkspaceServiceTestCase):
    def test_absolute_path_is_rejected(self):
        self.assert_error("invalid_path", lambda: self.service.read_file("/etc/hosts"))

    def test_parent_components_are_rejected(self):
        self.assert_error("invalid_path", lambda: self.service.read_file("safe/../file.txt"))

    def test_external_symlink_is_rejected(self):
        outside = self.container / "outside.txt"
        outside.write_text("outside")
        (self.root / "escape.txt").symlink_to(outside)
        self.assert_error(
            "path_escape",
            lambda: self.service.read_file("escape.txt"),
        )

    def test_traversal_and_absolute_paths_return_403_on_read_and_save(self):
        # SEGURIDAD (v3): salir del workspace con ../ o rutas absolutas se
        # rechaza con 403 Forbidden, tanto al LEER como al GUARDAR.
        for bad in ("/etc/passwd", "../outside.py", "safe/../../secret.py"):
            with self.subTest(path=bad):
                with self.assertRaises(WorkspaceError) as read_raised:
                    self.service.read_file(bad)
                self.assertEqual(read_raised.exception.status_code, 403)
                with self.assertRaises(WorkspaceError) as save_raised:
                    self.service.save_file(bad, "x = 1\n", "0" * 64)
                self.assertEqual(save_raised.exception.status_code, 403)

    def test_hardlinked_file_is_not_exposed_or_editable(self):
        protected = self.write_text(".env", "synthetic-parent-value")
        os.link(protected, self.root / "allowed.py")
        self.assert_error("protected_path", lambda: self.service.read_file("allowed.py"))
        self.assert_error(
            "protected_path",
            lambda: self.service.save_file("allowed.py", "replacement", "0" * 64),
        )

    @unittest.skipUnless(
        _DIR_FD_OK,
        "parent-directory identity (openat/dir_fd) hardening is Unix-only; "
        "the Windows path-based save layer can't hold a parent fd",
    )
    def test_parent_directory_identity_change_is_rejected(self):
        self.write_text("nested/file.txt", "text")
        with patch.object(
            self.service,
            "_parent_identity_matches",
            return_value=False,
        ):
            self.assert_error(
                "path_changed",
                lambda: self.service.read_file("nested/file.txt"),
            )

    def test_env_is_hidden_unreadable_and_unwritable(self):
        self.write_text(".env", "SYNTHETIC_VALUE=not-real")
        paths = {entry["path"] for entry in self.service.tree()["entries"]}
        self.assertNotIn(".env", paths)
        self.assert_error("protected_path", lambda: self.service.read_file(".env"))
        self.assert_error(
            "protected_path",
            lambda: self.service.save_file(".env", "changed", "0" * 64),
        )

    def test_database_and_sidecars_are_hidden_unreadable_and_unwritable(self):
        names = ("pool.sqlite3", "pool.sqlite3-wal", "pool.sqlite3-shm", "data.db")
        for name in names:
            self.write_bytes(name, b"synthetic")
        paths = {entry["path"] for entry in self.service.tree()["entries"]}
        for name in names:
            with self.subTest(name=name):
                self.assertNotIn(name, paths)
                self.assert_error("protected_path", lambda name=name: self.service.read_file(name))
                self.assert_error(
                    "protected_path",
                    lambda name=name: self.service.save_file(name, "x", "0" * 64),
                )

    def test_git_logs_caches_dependencies_and_virtualenv_are_excluded(self):
        protected_directories = (
            ".git",
            ".cache",
            ".codex",
            "logs",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
            "build",
            "dist",
            "venv",
        )
        for directory in protected_directories:
            self.write_text(f"{directory}/visible.txt", "hidden")
        self.write_text("trace.log", "hidden")
        paths = {entry["path"] for entry in self.service.tree()["entries"]}
        for directory in protected_directories:
            self.assertNotIn(directory, paths)
            self.assert_error(
                "protected_path",
                lambda directory=directory: self.service.read_file(
                    f"{directory}/visible.txt"
                ),
            )
        self.assertNotIn("trace.log", paths)

    def test_credentials_keys_archives_rotated_logs_and_temporaries_are_excluded(self):
        protected_files = (
            "credentials.json",
            "credential.json",
            "private_key.txt",
            "id_ecdsa",
            "bundle.tar.gz",
            "backup.zst",
            "trace.log.1",
            "events.jsonl.2",
            f"{TEMPORARY_PREFIX}interrupted.tmp",
        )
        for name in protected_files:
            self.write_text(name, "synthetic")
        paths = {entry["path"] for entry in self.service.tree()["entries"]}
        for name in protected_files:
            with self.subTest(name=name):
                self.assertNotIn(name, paths)
                self.assert_error("protected_path", lambda name=name: self.service.read_file(name))

    def test_env_example_remains_readable(self):
        self.write_text(".env.example", "EXAMPLE=placeholder\n")
        response = self.service.read_file(".env.example")
        self.assertEqual(response["path"], ".env.example")
        self.assertEqual(response["content"], "EXAMPLE=placeholder\n")

    def test_runtime_protected_path_is_never_exposed(self):
        runtime = self.root / "runtime" / "credentials"
        runtime.mkdir(parents=True)
        (runtime / "pool.dat").write_text("synthetic")
        service = WorkspaceService(self.root, protected_paths=(runtime,))
        paths = {entry["path"] for entry in service.tree()["entries"]}
        self.assertNotIn("runtime/credentials", paths)
        self.assert_error(
            "protected_path",
            lambda: service.read_file("runtime/credentials/pool.dat"),
        )


class WorkspaceTreeTests(WorkspaceServiceTestCase):
    def test_tree_is_deterministic_with_directories_first(self):
        (self.root / "z-dir").mkdir()
        (self.root / "A-dir").mkdir()
        self.write_text("z.txt", "z")
        self.write_text("A.txt", "a")
        paths = [entry["path"] for entry in self.service.tree()["entries"]]
        self.assertEqual(paths, ["A-dir", "z-dir", "A.txt", "z.txt"])

    def test_tree_depth_limit_is_reported(self):
        self.write_text("one/two/three.txt", "deep")
        service = WorkspaceService(self.root, max_tree_depth=1)
        response = service.tree()
        self.assertEqual([entry["path"] for entry in response["entries"]], ["one"])
        self.assertTrue(response["depth_limited"])

    def test_tree_entry_limit_is_enforced(self):
        for index in range(5):
            self.write_text(f"file-{index}.txt", "text")
        service = WorkspaceService(self.root, max_tree_entries=2)
        response = service.tree()
        self.assertEqual(len(response["entries"]), 2)
        self.assertTrue(response["truncated"])

    def test_tree_scan_is_bounded_before_directory_materialization(self):
        for index in range(5):
            self.write_text(f"file-{index}.txt", "text")
        service = WorkspaceService(
            self.root,
            max_tree_entries=10,
            max_tree_scanned_entries=2,
        )
        response = service.tree()
        self.assertLessEqual(len(response["entries"]), 2)
        self.assertTrue(response["truncated"])

    def test_binary_file_is_present_but_marked_noneditable(self):
        self.write_bytes("sample.bin", b"\x00\x01")
        entry = self.service.tree()["entries"][0]
        self.assertEqual(entry["path"], "sample.bin")
        self.assertFalse(entry["editable"])


class WorkspaceReadTests(WorkspaceServiceTestCase):
    def test_utf8_and_utf8_bom_are_read(self):
        self.write_text("utf8.txt", "línea\n")
        self.write_bytes("bom.txt", b"\xef\xbb\xbftexto")
        self.assertEqual(self.service.read_file("utf8.txt")["content"], "línea\n")
        self.assertEqual(self.service.read_file("bom.txt")["content"], "texto")

    def test_empty_file_is_valid_text(self):
        self.write_bytes("empty.txt", b"")
        response = self.service.read_file("empty.txt")
        self.assertEqual(response["content"], "")
        self.assertEqual(len(response["version"]), 64)

    def test_binary_and_invalid_utf8_are_rejected(self):
        self.write_bytes("nul.dat", b"text\x00data")
        self.write_bytes("invalid.dat", b"\xff\xfe")
        self.write_bytes("control.dat", b"text\x01data")
        for path in ("nul.dat", "invalid.dat", "control.dat"):
            with self.subTest(path=path):
                self.assert_error("binary_file", lambda path=path: self.service.read_file(path))

    def test_known_binary_extension_is_rejected_even_with_text_shaped_bytes(self):
        self.write_bytes("image.png", b"synthetic-ascii")
        self.assert_error("binary_file", lambda: self.service.read_file("image.png"))
        self.assert_error(
            "binary_file",
            lambda: self.service.save_file("image.png", "text", "0" * 64),
        )

    def test_oversized_file_is_rejected_before_full_read(self):
        self.write_bytes("large.txt", b"x" * 11)
        service = WorkspaceService(self.root, max_file_bytes=10)
        with self.assertRaises(WorkspaceError) as raised:
            service.read_file("large.txt")
        self.assertEqual(raised.exception.code, "file_too_large")

    def test_directory_cannot_be_read_as_a_file(self):
        (self.root / "folder").mkdir()
        self.assert_error("not_a_file", lambda: self.service.read_file("folder"))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support is required")
    def test_fifo_is_rejected_without_blocking(self):
        os.mkfifo(self.root / "named-pipe")
        self.assert_error("not_a_file", lambda: self.service.read_file("named-pipe"))


class WorkspaceWriteTests(WorkspaceServiceTestCase):
    def test_existing_file_is_replaced_atomically_and_mode_is_preserved(self):
        path = self.write_text("source.py", "before\n", mode=0o640)
        original = self.service.read_file("source.py")
        response = self.service.save_file(
            "source.py",
            "after\n",
            original["version"],
        )
        self.assertEqual(path.read_text(), "after\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual(response["path"], "source.py")
        self.assertEqual(len(response["version"]), 64)
        self.assertEqual(list(self.root.glob(f"{TEMPORARY_PREFIX}*")), [])

    def test_multi_file_preflight_rejects_before_first_write(self):
        first = self.write_text("first.txt", "one")
        second = self.write_text("second.txt", "two")
        service = WorkspaceService(self.root, max_file_bytes=5)
        originals = [service.read_file("first.txt"), service.read_file("second.txt")]
        edits = [
            {"path": "first.txt", "content": "new", "base_version": originals[0]["version"]},
            {"path": "second.txt", "content": "too-long", "base_version": originals[1]["version"]},
        ]
        self.assert_error("file_too_large", lambda: service.save_files_atomically(edits))
        self.assertEqual(first.read_text(), "one")
        self.assertEqual(second.read_text(), "two")

    def test_multi_file_failure_restores_completed_replacements(self):
        first = self.write_text("first.txt", "one")
        second = self.write_text("second.txt", "two")
        originals = [self.service.read_file("first.txt"), self.service.read_file("second.txt")]
        edits = [
            {"path": "first.txt", "content": "new-one", "base_version": originals[0]["version"]},
            {"path": "second.txt", "content": "new-two", "base_version": originals[1]["version"]},
        ]
        real_save = self.service.save_file

        def fail_second(path, content, base_version):
            if path == "second.txt" and content == "new-two":
                raise RuntimeError("synthetic internal detail")
            return real_save(path, content, base_version)

        with patch.object(self.service, "save_file", side_effect=fail_second):
            self.assert_error(
                "atomic_save_failed",
                lambda: self.service.save_files_atomically(edits),
            )
        self.assertEqual(first.read_text(), "one")
        self.assertEqual(second.read_text(), "two")

    def test_temporary_file_remains_owner_only_before_replacement(self):
        self.write_text("source.txt", "before", mode=0o644)
        original = self.service.read_file("source.txt")
        real_replace = os.replace
        observed_modes = []

        def inspect_then_replace(source, destination, **kwargs):
            observed_modes.append(
                stat.S_IMODE((self.root / source).stat().st_mode)
            )
            return real_replace(source, destination, **kwargs)

        with patch("app.core.workspace.os.replace", side_effect=inspect_then_replace):
            self.service.save_file("source.txt", "after", original["version"])
        self.assertEqual(observed_modes, [0o600])

    def test_version_conflict_preserves_external_and_local_content(self):
        path = self.write_text("conflict.txt", "base")
        original = self.service.read_file("conflict.txt")
        path.write_text("external")
        self.assert_error(
            "version_conflict",
            lambda: self.service.save_file("conflict.txt", "local", original["version"]),
        )
        self.assertEqual(path.read_text(), "external")

    def test_missing_file_is_not_created(self):
        self.assert_error(
            "not_found",
            lambda: self.service.save_file("missing.txt", "new", "0" * 64),
        )
        self.assertFalse((self.root / "missing.txt").exists())

    def test_directory_is_not_overwritten(self):
        (self.root / "folder").mkdir()
        self.assert_error(
            "not_a_file",
            lambda: self.service.save_file("folder", "new", "0" * 64),
        )
        self.assertTrue((self.root / "folder").is_dir())

    def test_temporary_file_is_removed_after_replace_failure(self):
        self.write_text("source.txt", "before")
        original = self.service.read_file("source.txt")
        with patch("app.core.workspace.os.replace", side_effect=OSError("synthetic")):
            self.assert_error(
                "save_failed",
                lambda: self.service.save_file(
                    "source.txt", "after", original["version"]
                ),
            )
        self.assertEqual(list(self.root.glob(f"{TEMPORARY_PREFIX}*")), [])
        self.assertEqual((self.root / "source.txt").read_text(), "before")

    def test_symlink_swap_during_replace_cannot_escape_workspace(self):
        target = self.write_text("target.txt", "before")
        outside = self.container / "outside.txt"
        outside.write_text("outside")
        original = self.service.read_file("target.txt")
        real_replace = os.replace

        def swap_then_replace(source, destination, **kwargs):
            target.unlink()
            target.symlink_to(outside)
            return real_replace(source, destination, **kwargs)

        with patch("app.core.workspace.os.replace", side_effect=swap_then_replace):
            self.service.save_file("target.txt", "after", original["version"])
        self.assertEqual(outside.read_text(), "outside")
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), "after")

    def test_utf8_bom_is_preserved_on_save(self):
        path = self.write_bytes("bom.txt", b"\xef\xbb\xbfbefore")
        original = self.service.read_file("bom.txt")
        self.service.save_file("bom.txt", "after", original["version"])
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_unencodable_unicode_is_rejected_without_changing_file(self):
        path = self.write_text("source.txt", "before")
        original = self.service.read_file("source.txt")
        self.assert_error(
            "invalid_request",
            lambda: self.service.save_file(
                "source.txt",
                "invalid-\ud800",
                original["version"],
            ),
        )
        self.assertEqual(path.read_text(), "before")


class WorkspaceApiSecurityTests(WorkspaceServiceTestCase):
    def test_all_routes_are_localhost_only_and_put_requires_local_origin(self):
        for route in workspace_api.router.routes:
            dependencies = {dependency.call for dependency in route.dependant.dependencies}
            self.assertIn(require_localhost, dependencies)
            if "PUT" in getattr(route, "methods", set()):
                self.assertIn(require_local_origin, dependencies)

    def test_local_origin_and_originless_local_client_are_allowed(self):
        self.assertIsNone(
            require_local_origin(_request(origin="http://127.0.0.1:8000"))
        )
        self.assertIsNone(require_local_origin(_request()))

    def test_non_local_origin_and_client_are_rejected(self):
        with self.assertRaises(HTTPException):
            require_local_origin(_request(origin="https://example.invalid"))
        with self.assertRaises(HTTPException):
            require_localhost(_request(host="192.0.2.20"))

    def test_api_payloads_never_include_absolute_root(self):
        self.write_text("source.py", "print('synthetic')\n")
        tree = self.service.tree()
        read = self.service.read_file("source.py")
        serialized = json.dumps({"tree": tree, "read": read})
        self.assertNotIn(str(self.root), serialized)

    def test_session_log_does_not_include_file_content(self):
        synthetic_content = "synthetic-workspace-content-not-a-secret"
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Capture()
        logger.addHandler(handler)
        middleware = SessionLoggingMiddleware(lambda _scope, _receive, _send: None)

        async def call_next(_request):
            return Response(status_code=200)

        try:
            asyncio.run(middleware.dispatch(_request(), call_next))
        finally:
            logger.removeHandler(handler)
        self.assertTrue(records)
        self.assertNotIn(synthetic_content, "".join(records))

    def test_validation_error_does_not_echo_submitted_content(self):
        from app.main import safe_provider_key_validation_error

        synthetic_content = "synthetic-invalid-workspace-body"
        error = RequestValidationError(
            [
                {
                    "type": "string_type",
                    "loc": ("body", "content"),
                    "msg": "Input should be a valid string",
                    "input": synthetic_content,
                }
            ]
        )
        response = asyncio.run(
            safe_provider_key_validation_error(_request(), error)
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(synthetic_content, response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
