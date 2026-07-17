"""
Skill System — GERAM Core System.

A Skill is NOT a prompt. It is reusable, versioned, validated, portable
knowledge inside the GERAM ecosystem. The entire future Developer Packs
architecture will be distributed as Skills, so this contract is designed to be
stable and forward-compatible from day one.

Two origins exist:

  * ``system``  — shipped in-code, trusted, read-only.
  * ``custom``  — authored by the user, persisted under ``LOCAL_DATA_DIR``,
    and treated as UNTRUSTED CONTENT. Its Markdown ``body`` is inert data:
    it is stored, retrieved, and shown, but it is NEVER executed and never
    automatically trusted.

A Skill declares the tools and permissions it *expects*, but declaring a
permission grants nothing — the Permission Registry and Context Builder decide
what an agent may actually do.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.gcs.permissions import permission_registry
from app.core.gcs.storage import (
    StorageError,
    delete_document,
    document_path,
    gcs_data_dir,
    list_document_ids,
    read_json,
    validate_id,
    write_json_atomic_0600,
)

# Profiles a Skill can be compatible with. "any" means both IRIS and A.R.E.S.
SKILL_PROFILES = ("iris", "ares", "any")
SKILL_ORIGINS = ("system", "custom")
SKILL_STATUSES = ("enabled", "disabled")

MAX_TRIGGERS = 32
MAX_TOOLS = 32
MAX_BODY_LENGTH = 20_000


class Skill(BaseModel):
    """The portable Skill contract."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    version: str = Field(default="1.0.0", max_length=32)
    profile: str = "any"
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    origin: str = "custom"
    status: str = "enabled"
    # Inert knowledge payload. NEVER executed — retrieved and displayed only.
    body: str = Field(default="", max_length=MAX_BODY_LENGTH)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return validate_id(value, kind="skill_id")

    @field_validator("profile")
    @classmethod
    def _validate_profile(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SKILL_PROFILES:
            raise ValueError(f"profile must be one of {SKILL_PROFILES}")
        return normalized

    @field_validator("origin")
    @classmethod
    def _validate_origin(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SKILL_ORIGINS:
            raise ValueError(f"origin must be one of {SKILL_ORIGINS}")
        return normalized

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SKILL_STATUSES:
            raise ValueError(f"status must be one of {SKILL_STATUSES}")
        return normalized

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, value: list[str]) -> list[str]:
        # Fail-closed: an unknown permission slug rejects the whole skill.
        return [p.value for p in permission_registry.normalize_many(value)]

    @field_validator("triggers")
    @classmethod
    def _validate_triggers(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            entry = str(raw).strip().lower()
            if entry and entry not in cleaned:
                cleaned.append(entry)
        if len(cleaned) > MAX_TRIGGERS:
            raise ValueError(f"a skill cannot declare more than {MAX_TRIGGERS} triggers")
        return cleaned

    @field_validator("tools")
    @classmethod
    def _validate_tools(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            entry = str(raw).strip()
            if entry and entry not in cleaned:
                cleaned.append(entry)
        if len(cleaned) > MAX_TOOLS:
            raise ValueError(f"a skill cannot declare more than {MAX_TOOLS} tools")
        return cleaned

    def supports_profile(self, profile: str) -> bool:
        target = profile.strip().lower()
        return self.profile == "any" or self.profile == target

    def summary(self) -> dict:
        """Metadata view without the (potentially large) inert body."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "profile": self.profile,
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "triggers": list(self.triggers),
            "origin": self.origin,
            "status": self.status,
        }


def _system_skills() -> list[Skill]:
    """The built-in, trusted Skill library. Kept small and demonstrative.

    These validate the contract and give the Skill Retriever real, useful
    matches out of the box, fully offline.
    """
    return [
        Skill(
            id="html-boilerplate",
            name="HTML5 Boilerplate",
            description="Starter HTML5 document with responsive viewport meta.",
            version="1.0.0",
            profile="ares",
            tools=["editor"],
            permissions=["read", "write"],
            triggers=["html", "boilerplate", "html5", "starter html", "scaffold html"],
            origin="system",
            body=(
                "# HTML5 Boilerplate\n\n"
                "```html\n"
                "<!DOCTYPE html>\n"
                "<html lang=\"es\">\n"
                "<head>\n"
                "  <meta charset=\"UTF-8\">\n"
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
                "  <title>Document</title>\n"
                "</head>\n"
                "<body>\n\n"
                "</body>\n"
                "</html>\n"
                "```\n"
            ),
        ),
        Skill(
            id="python-cli-argparse",
            name="Python CLI with argparse",
            description="Minimal, well-structured Python command-line entry point.",
            version="1.0.0",
            profile="ares",
            tools=["editor", "terminal"],
            permissions=["read", "write", "terminal"],
            triggers=["python cli", "argparse", "command line", "cli", "entry point"],
            origin="system",
            body=(
                "# Python CLI (argparse)\n\n"
                "```python\n"
                "import argparse\n\n\n"
                "def main() -> None:\n"
                "    parser = argparse.ArgumentParser(description=\"...\")\n"
                "    parser.add_argument(\"name\")\n"
                "    args = parser.parse_args()\n"
                "    print(f\"Hola, {args.name}\")\n\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n"
                "```\n"
            ),
        ),
        Skill(
            id="fastapi-endpoint",
            name="FastAPI endpoint",
            description="Idiomatic FastAPI router with a Pydantic request model.",
            version="1.0.0",
            profile="ares",
            tools=["editor"],
            permissions=["read", "write"],
            triggers=["fastapi", "endpoint", "router", "api route", "rest api"],
            origin="system",
            body=(
                "# FastAPI endpoint\n\n"
                "```python\n"
                "from fastapi import APIRouter\n"
                "from pydantic import BaseModel\n\n"
                "router = APIRouter(prefix=\"/items\", tags=[\"items\"])\n\n\n"
                "class ItemIn(BaseModel):\n"
                "    name: str\n\n\n"
                "@router.post(\"/\")\n"
                "async def create_item(item: ItemIn):\n"
                "    return {\"created\": item.name}\n"
                "```\n"
            ),
        ),
        Skill(
            id="css-flow-layout",
            name="CSS centered flex layout",
            description="Reliable full-viewport centering with flexbox.",
            version="1.0.0",
            profile="ares",
            tools=["editor"],
            permissions=["read", "write"],
            triggers=["css", "center", "flexbox", "flex", "layout", "centrar"],
            origin="system",
            body=(
                "# Centered flex layout\n\n"
                "```css\n"
                ".stage {\n"
                "  min-height: 100vh;\n"
                "  display: flex;\n"
                "  align-items: center;\n"
                "  justify-content: center;\n"
                "}\n"
                "```\n"
            ),
        ),
    ]


class SkillStore:
    """System (trusted, in-code) + custom (untrusted, on-disk) skills."""

    def __init__(self) -> None:
        self._system: dict[str, Skill] = {s.id: s for s in _system_skills()}

    # -- storage location -------------------------------------------------
    def _custom_dir(self) -> Path:
        return gcs_data_dir("skills", "custom")

    # -- reads ------------------------------------------------------------
    def list_system(self) -> list[Skill]:
        return list(self._system.values())

    def list_custom(self) -> list[Skill]:
        """Load every persisted custom skill, skipping unreadable/invalid ones."""
        skills: list[Skill] = []
        directory = self._custom_dir()
        for skill_id in list_document_ids(directory):
            try:
                raw = read_json(document_path(directory, skill_id, kind="skill_id"))
                skill = Skill.model_validate(raw)
            except (StorageError, ValueError):
                # A single corrupt custom skill must never break the catalog.
                continue
            # Custom content is untrusted: force-correct origin so a crafted
            # file can never masquerade as a trusted system skill.
            if skill.origin != "custom":
                skill = skill.model_copy(update={"origin": "custom"})
            skills.append(skill)
        return skills

    def list_all(self) -> list[Skill]:
        return self.list_system() + self.list_custom()

    def get(self, skill_id: str) -> Skill | None:
        try:
            safe_id = validate_id(skill_id, kind="skill_id")
        except StorageError:
            return None
        if safe_id in self._system:
            return self._system[safe_id]
        directory = self._custom_dir()
        path = document_path(directory, safe_id, kind="skill_id")
        if not path.exists():
            return None
        try:
            raw = read_json(path)
            skill = Skill.model_validate(raw)
        except (StorageError, ValueError):
            return None
        if skill.origin != "custom":
            skill = skill.model_copy(update={"origin": "custom"})
        return skill

    # -- writes (custom only) --------------------------------------------
    def save_custom(self, skill: Skill) -> Skill:
        """Persist a custom skill. System ids are protected from being shadowed."""
        if skill.id in self._system:
            raise StorageError(
                "reserved_skill_id",
                "this id belongs to a protected system skill",
            )
        # Origin is always forced to custom on write — never trust the input.
        skill = skill.model_copy(update={"origin": "custom"})
        directory = self._custom_dir()
        path = document_path(directory, skill.id, kind="skill_id")
        write_json_atomic_0600(path, skill.model_dump(mode="json"))
        return skill

    def delete_custom(self, skill_id: str) -> bool:
        safe_id = validate_id(skill_id, kind="skill_id")
        if safe_id in self._system:
            raise StorageError("reserved_skill_id", "system skills cannot be deleted")
        return delete_document(document_path(self._custom_dir(), safe_id, kind="skill_id"))


# Singleton shared across the app lifespan.
skill_store = SkillStore()
