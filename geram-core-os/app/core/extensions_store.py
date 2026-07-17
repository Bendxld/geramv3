"""
VS Code extension importer/store for GERAM CORE OS.

Monaco is the editor VS Code is built on, but it is NOT VS Code — it cannot run
a `.vsix`'s activation code, commands, views or language servers. What it CAN
consume are the *declarative* contributions a `.vsix` ships in its
`package.json` under `contributes`:

  * themes   -> converted to `monaco.editor.defineTheme` payloads
  * snippets -> registered as Monaco completion providers
  * grammars -> TextMate tokenization (real syntax highlighting)
  * languages -> language ids + Monaco language configuration

A `.vsix` is just a ZIP with everything under `extension/`. We read it in
memory (never extracting attacker-controlled paths to disk), pull those four
declarative pieces, convert them, and persist one JSON manifest per extension
under `LOCAL_DATA_DIR/extensions/`. Loose theme/snippet/grammar JSON files are
accepted too, for people who only have the file, not the whole `.vsix`.

Everything here is local, offline and fail-safe: a malformed extension raises a
sanitized error and never touches the store.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from app.core.config import settings

EXT_SUBDIR = "extensions"
# Grammars can be large (some TextMate grammars are >200 KB); allow generous
# room per manifest while still bounding memory against hostile bloat.
MAX_MANIFEST_BYTES = 6 * 1024 * 1024
MAX_UPLOAD_BYTES = 40 * 1024 * 1024

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,98}$")
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3,8})$")


class ExtensionError(ValueError):
    """A sanitized import/store failure safe to show to the local user."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def _dir() -> Path:
    base = (settings.LOCAL_DATA_DIR / EXT_SUBDIR).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _slug(value: str, fallback: str = "extension") -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(value).strip().lower()).strip("-.")
    slug = slug[:98]
    return slug if _ID_PATTERN.fullmatch(slug or "") else fallback


def _manifest_path(ext_id: str) -> Path:
    if not _ID_PATTERN.fullmatch(ext_id):
        raise ExtensionError("invalid_id", "Extension id is not a safe slug.")
    directory = _dir()
    path = (directory / f"{ext_id}.json").resolve()
    path.relative_to(directory)  # traversal guard
    return path


def _write_manifest(manifest: dict) -> None:
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ExtensionError("too_large", "The extension is too large to store.")
    path = _manifest_path(manifest["id"])
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".ext-", suffix=".tmp")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_manifest(path: Path) -> dict | None:
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def list_extensions() -> list[dict]:
    """Public summaries (no heavy grammar bodies) of every stored extension."""
    out: list[dict] = []
    for entry in sorted(_dir().glob("*.json")):
        if entry.name.startswith("."):
            continue
        manifest = _read_manifest(entry)
        if manifest:
            out.append(_summary(manifest))
    return out


def get_extension(ext_id: str) -> dict | None:
    manifest = _read_manifest(_manifest_path(_slug(ext_id, ext_id)))
    return manifest


def delete_extension(ext_id: str) -> bool:
    try:
        _manifest_path(_slug(ext_id, ext_id)).unlink()
        return True
    except FileNotFoundError:
        return False
    except ExtensionError:
        return False


def _summary(manifest: dict) -> dict:
    return {
        "id": manifest.get("id"),
        "name": manifest.get("name"),
        "publisher": manifest.get("publisher"),
        "version": manifest.get("version"),
        "origin": manifest.get("origin", "vsix"),
        "themes": [
            {"id": t["id"], "label": t.get("label", t["id"]), "type": t.get("type", "dark")}
            for t in manifest.get("themes", [])
        ],
        "snippets": [
            {"language": s.get("language", "*"), "count": len(s.get("snippets", {}))}
            for s in manifest.get("snippets", [])
        ],
        "grammars": [
            {"language": g.get("language"), "scopeName": g.get("scopeName")}
            for g in manifest.get("grammars", [])
        ],
        "languages": [
            {"id": lang.get("id"), "extensions": lang.get("extensions", [])}
            for lang in manifest.get("languages", [])
        ],
    }


# Aggregated views consumed by the Monaco front-end.
def all_themes() -> list[dict]:
    out: list[dict] = []
    for summary in _iter_manifests():
        for theme in summary.get("themes", []):
            out.append({**theme, "extension": summary["id"]})
    return out


def all_snippets() -> list[dict]:
    out: list[dict] = []
    for manifest in _iter_manifests():
        for snip in manifest.get("snippets", []):
            out.append({**snip, "extension": manifest["id"]})
    return out


def all_grammars() -> list[dict]:
    out: list[dict] = []
    for manifest in _iter_manifests():
        for grammar in manifest.get("grammars", []):
            out.append({**grammar, "extension": manifest["id"]})
    return out


def all_languages() -> list[dict]:
    out: list[dict] = []
    for manifest in _iter_manifests():
        for lang in manifest.get("languages", []):
            out.append({**lang, "extension": manifest["id"]})
    return out


def _iter_manifests() -> list[dict]:
    manifests: list[dict] = []
    for entry in sorted(_dir().glob("*.json")):
        if entry.name.startswith("."):
            continue
        manifest = _read_manifest(entry)
        if manifest:
            manifests.append(manifest)
    return manifests


# --------------------------------------------------------------------------- #
# JSONC parsing (VS Code theme/snippet/language files are frequently JSONC)
# --------------------------------------------------------------------------- #
def _loads_jsonc(text: str) -> Any:
    """Parse JSON that may contain // and /* */ comments and trailing commas."""
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    lines = []
    for line in without_block.splitlines():
        # Strip // comments that are not inside a string (best-effort: ignore
        # // preceded by an even number of unescaped quotes on the line).
        in_string = False
        escaped = False
        cut = None
        for i, ch in enumerate(line):
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if ch == "/" and not in_string and i + 1 < len(line) and line[i + 1] == "/":
                cut = i
                break
        lines.append(line if cut is None else line[:cut])
    cleaned = "\n".join(lines)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)  # trailing commas
    return json.loads(cleaned)


# --------------------------------------------------------------------------- #
# VS Code theme  ->  Monaco theme
# --------------------------------------------------------------------------- #
def _norm_hex(value: str, *, keep_hash: bool) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _HEX_COLOR.fullmatch(value):
        return None
    return value if keep_hash else value.lstrip("#")


def vscode_theme_to_monaco(theme: dict, *, label: str) -> dict:
    """Convert a VS Code color-theme JSON to a monaco.editor.defineTheme payload."""
    kind = str(theme.get("type", "dark")).lower()
    base = {"light": "vs", "dark": "vs-dark", "hc": "hc-black", "hcLight": "hc-light"}.get(kind, "vs-dark")

    rules: list[dict] = []
    for token in theme.get("tokenColors", []) or []:
        if not isinstance(token, dict):
            continue
        settings_block = token.get("settings", {}) or {}
        scopes = token.get("scope", "")
        if isinstance(scopes, str):
            scopes = [s.strip() for s in scopes.split(",") if s.strip()] or [""]
        elif not isinstance(scopes, list):
            scopes = [""]
        for scope in scopes:
            rule: dict[str, str] = {"token": str(scope)}
            fg = _norm_hex(settings_block.get("foreground", ""), keep_hash=False)
            bg = _norm_hex(settings_block.get("background", ""), keep_hash=False)
            if fg:
                rule["foreground"] = fg
            if bg:
                rule["background"] = bg
            font = settings_block.get("fontStyle")
            if isinstance(font, str) and font.strip():
                rule["fontStyle"] = font.strip()
            if len(rule) > 1:
                rules.append(rule)

    colors: dict[str, str] = {}
    for key, value in (theme.get("colors", {}) or {}).items():
        hexed = _norm_hex(value, keep_hash=True)
        if isinstance(key, str) and hexed:
            colors[key] = hexed

    return {"base": base, "inherit": True, "rules": rules, "colors": colors, "type": kind, "label": label}


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
def _read_zip_member(zf: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_UPLOAD_BYTES:
        raise ExtensionError("too_large", "A file inside the extension is too large.")
    with zf.open(info) as handle:
        return handle.read()


def _resolve_member(zf: zipfile.ZipFile, base: str, rel: str) -> str | None:
    """Resolve a contributes path relative to the extension root, safely."""
    rel = str(rel).lstrip("./")
    candidate = os.path.normpath(f"{base}/{rel}")
    if candidate.startswith("..") or candidate not in zf.namelist():
        # Some VSIX list paths without the "extension/" prefix — try raw too.
        raw = os.path.normpath(rel)
        return raw if raw in zf.namelist() and not raw.startswith("..") else None
    return candidate


def _parse_grammar_bytes(data: bytes) -> dict | None:
    text = data.decode("utf-8", errors="replace").lstrip()
    if text.startswith("<?xml") or text.startswith("<!DOCTYPE") or text.startswith("<plist"):
        try:
            parsed = plistlib.loads(data)
            return parsed if isinstance(parsed, dict) else None
        except Exception:  # plistlib/expat raise a few unrelated types on bad XML
            return None
    try:
        parsed = _loads_jsonc(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def import_vsix(data: bytes) -> dict:
    """Parse a .vsix (zip) and store its declarative contributions."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtensionError("too_large", "The .vsix file is too large.")
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        raise ExtensionError("bad_vsix", "That file is not a valid .vsix archive.") from None

    with zf:
        pkg_bytes = _read_zip_member(zf, "extension/package.json")
        base = "extension"
        if pkg_bytes is None:
            pkg_bytes = _read_zip_member(zf, "package.json")
            base = "."
        if pkg_bytes is None:
            raise ExtensionError("no_package", "The .vsix has no package.json (contributes).")
        try:
            pkg = _loads_jsonc(pkg_bytes.decode("utf-8"))
        except ValueError:
            raise ExtensionError("bad_package", "The extension's package.json is invalid.") from None

        contributes = pkg.get("contributes", {}) if isinstance(pkg, dict) else {}
        name = str(pkg.get("displayName") or pkg.get("name") or "extension")
        publisher = str(pkg.get("publisher") or "")
        ext_id = _slug(f"{publisher}.{pkg.get('name', name)}" if publisher else name, "extension")

        themes = _collect_themes(zf, base, contributes.get("themes", []))
        snippets = _collect_snippets(zf, base, contributes.get("snippets", []))
        languages = _collect_languages(zf, base, contributes.get("languages", []))
        grammars = _collect_grammars(zf, base, contributes.get("grammars", []))

    if not (themes or snippets or grammars or languages):
        raise ExtensionError(
            "no_contributions",
            "This extension has no importable themes, snippets, grammars or languages "
            "(commands, views and language servers can't run on Monaco).",
        )

    manifest = {
        "id": ext_id,
        "name": name,
        "publisher": publisher,
        "version": str(pkg.get("version", "")),
        "origin": "vsix",
        "themes": themes,
        "snippets": snippets,
        "grammars": grammars,
        "languages": languages,
    }
    _write_manifest(manifest)
    return _summary(manifest)


def _collect_themes(zf: zipfile.ZipFile, base: str, contrib: list) -> list[dict]:
    themes: list[dict] = []
    for entry in contrib or []:
        if not isinstance(entry, dict) or "path" not in entry:
            continue
        member = _resolve_member(zf, base, entry["path"])
        raw = _read_zip_member(zf, member) if member else None
        if not raw:
            continue
        try:
            theme_json = _loads_jsonc(raw.decode("utf-8"))
        except ValueError:
            continue
        label = str(entry.get("label") or entry.get("id") or Path(entry["path"]).stem)
        theme_id = _slug(entry.get("id") or label, "theme")
        monaco = vscode_theme_to_monaco(theme_json, label=label)
        themes.append({"id": theme_id, **monaco})
    return themes


def _collect_snippets(zf: zipfile.ZipFile, base: str, contrib: list) -> list[dict]:
    snippets: list[dict] = []
    for entry in contrib or []:
        if not isinstance(entry, dict) or "path" not in entry:
            continue
        member = _resolve_member(zf, base, entry["path"])
        raw = _read_zip_member(zf, member) if member else None
        if not raw:
            continue
        try:
            body = _loads_jsonc(raw.decode("utf-8"))
        except ValueError:
            continue
        if isinstance(body, dict):
            snippets.append({
                "language": str(entry.get("language", "*")),
                "snippets": _normalize_snippets(body),
            })
    return snippets


def _normalize_snippets(body: dict) -> dict:
    out: dict[str, dict] = {}
    for name, snip in body.items():
        if not isinstance(snip, dict):
            continue
        raw_body = snip.get("body", "")
        text = "\n".join(raw_body) if isinstance(raw_body, list) else str(raw_body)
        out[str(name)] = {
            "prefix": snip.get("prefix", name) if isinstance(snip.get("prefix"), str)
            else (snip.get("prefix", [name])[0] if snip.get("prefix") else name),
            "body": text,
            "description": str(snip.get("description", "")),
        }
    return out


def _collect_languages(zf: zipfile.ZipFile, base: str, contrib: list) -> list[dict]:
    languages: list[dict] = []
    for entry in contrib or []:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        lang = {
            "id": str(entry["id"]),
            "extensions": [str(x) for x in entry.get("extensions", []) if isinstance(x, str)],
            "aliases": [str(x) for x in entry.get("aliases", []) if isinstance(x, str)],
            "configuration": None,
        }
        cfg_path = entry.get("configuration")
        if isinstance(cfg_path, str):
            member = _resolve_member(zf, base, cfg_path)
            raw = _read_zip_member(zf, member) if member else None
            if raw:
                try:
                    lang["configuration"] = _loads_jsonc(raw.decode("utf-8"))
                except ValueError:
                    lang["configuration"] = None
        languages.append(lang)
    return languages


def _collect_grammars(zf: zipfile.ZipFile, base: str, contrib: list) -> list[dict]:
    grammars: list[dict] = []
    for entry in contrib or []:
        if not isinstance(entry, dict) or "path" not in entry:
            continue
        member = _resolve_member(zf, base, entry["path"])
        raw = _read_zip_member(zf, member) if member else None
        if not raw:
            continue
        grammar = _parse_grammar_bytes(raw)
        if not grammar:
            continue
        grammars.append({
            "language": entry.get("language"),
            "scopeName": entry.get("scopeName") or grammar.get("scopeName"),
            "grammar": grammar,
        })
    return grammars


# --------------------------------------------------------------------------- #
# Loose-file import (a single theme / snippet / grammar JSON)
# --------------------------------------------------------------------------- #
def import_json_file(data: bytes, filename: str) -> dict:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExtensionError("too_large", "The file is too large.")
    try:
        parsed = _loads_jsonc(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ExtensionError("bad_json", "That file is not valid JSON.") from None
    if not isinstance(parsed, dict):
        raise ExtensionError("bad_json", "Expected a JSON object.") from None

    stem = _slug(Path(filename).stem or "imported", "imported")
    label = Path(filename).stem or stem

    manifest = {
        "id": stem, "name": label, "publisher": "", "version": "",
        "origin": "json", "themes": [], "snippets": [], "grammars": [], "languages": [],
    }
    # Theme? (has tokenColors, or type + colors)
    if "tokenColors" in parsed or ("type" in parsed and "colors" in parsed):
        manifest["themes"] = [{"id": stem, **vscode_theme_to_monaco(parsed, label=label)}]
    # Grammar? (has scopeName + patterns)
    elif "scopeName" in parsed and "patterns" in parsed:
        manifest["grammars"] = [{
            "language": parsed.get("name"),
            "scopeName": parsed.get("scopeName"),
            "grammar": parsed,
        }]
    # Otherwise treat as a snippets file ({ name: {prefix, body} }).
    else:
        norm = _normalize_snippets(parsed)
        if not norm:
            raise ExtensionError(
                "unknown_json",
                "Couldn't tell if this is a theme, snippet or grammar file.",
            )
        manifest["snippets"] = [{"language": "*", "snippets": norm}]

    _write_manifest(manifest)
    return _summary(manifest)


# --------------------------------------------------------------------------- #
# Create-your-own (custom theme / snippet)
# --------------------------------------------------------------------------- #
def save_custom_theme(theme_id: str, label: str, theme: dict) -> dict:
    ext_id = _slug(theme_id, "custom-theme")
    monaco = vscode_theme_to_monaco(theme, label=label or ext_id)
    manifest = {
        "id": ext_id, "name": label or ext_id, "publisher": "you", "version": "",
        "origin": "custom", "snippets": [], "grammars": [], "languages": [],
        "themes": [{"id": ext_id, **monaco}],
    }
    _write_manifest(manifest)
    return _summary(manifest)


def save_custom_snippet(snippet_id: str, language: str, snippets: dict) -> dict:
    ext_id = _slug(snippet_id, "custom-snippets")
    manifest = {
        "id": ext_id, "name": snippet_id or ext_id, "publisher": "you", "version": "",
        "origin": "custom", "themes": [], "grammars": [], "languages": [],
        "snippets": [{"language": str(language or "*"), "snippets": _normalize_snippets(snippets)}],
    }
    _write_manifest(manifest)
    return _summary(manifest)
