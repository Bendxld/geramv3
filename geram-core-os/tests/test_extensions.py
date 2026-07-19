"""Limits and happy-path coverage for declarative VSIX imports."""

import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app.core import extensions_store as store


def _vsix(extra_files=None):
    package = {
        "name": "sample",
        "publisher": "tests",
        "version": "1.0.0",
        "contributes": {
            "snippets": [{"language": "python", "path": "snippets.json"}]
        },
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extension/package.json", json.dumps(package))
        archive.writestr(
            "extension/snippets.json",
            json.dumps({"hello": {"prefix": "hello", "body": "print('hello')"}}),
        )
        for name, content in extra_files or []:
            archive.writestr(name, content)
    return output.getvalue()


class ExtensionArchiveLimitTests(unittest.TestCase):
    def test_valid_declarative_vsix_is_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(store.settings, "LOCAL_DATA_DIR", Path(directory)):
                result = store.import_vsix(_vsix())
        self.assertEqual(result["id"], "tests.sample")
        self.assertEqual(result["snippets"][0]["count"], 1)

    def test_member_count_is_bounded_before_import(self):
        with patch.object(store, "MAX_ARCHIVE_MEMBERS", 2):
            with self.assertRaises(store.ExtensionError) as raised:
                store.import_vsix(_vsix([("extension/extra.txt", "x")]))
        self.assertEqual(raised.exception.code, "too_many_files")

    def test_total_uncompressed_size_is_bounded(self):
        with patch.object(store, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 20):
            with self.assertRaises(store.ExtensionError) as raised:
                store.import_vsix(_vsix())
        self.assertEqual(raised.exception.code, "too_large_uncompressed")


if __name__ == "__main__":
    unittest.main()
