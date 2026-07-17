"""
Agent Factory — GERAM Core System.

The single most important capability of GERAM: instead of shipping hundreds of
pre-installed agents, GERAM lets any user *build their own team*.

    Create Agent -> Validate -> Save -> Enable
                 -> assign Skills / Tools / Integrations / Permissions
                 -> use it from IRIS or A.R.E.S.

Invariants that must hold for the next five years:

  * An agent is NEVER a profile. It always **belongs to** exactly one profile
    (``iris`` or ``ares``) and never transforms the whole interface.
  * Only IRIS and A.R.E.S. are permanent profiles. No third profile is ever
    created here.
  * Custom agents are user content, persisted under ``LOCAL_DATA_DIR`` and
    validated on every write. References (skills, integrations, permissions)
    are checked for integrity so a saved agent is always coherent.

One system example agent — **Mustafa**, a helper for A.R.E.S. — ships in-code
to validate the architecture. It is explicitly a *helper agent*, not a third
profile.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.gcs.integrations import integration_hub
from app.core.gcs.permissions import permission_registry
from app.core.gcs.skills import skill_store
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

# An agent belongs to exactly one permanent profile. "any" is deliberately NOT
# allowed — agents are owned, never ambient.
AGENT_PROFILES = ("iris", "ares")
AGENT_ORIGINS = ("system", "custom")
AGENT_STATUSES = ("enabled", "disabled")

MAX_ASSIGNMENTS = 64


class AgentDefinition(BaseModel):
    """The Agent contract."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    profile: str
    description: str = Field(default="", max_length=500)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    origin: str = "custom"
    status: str = "enabled"

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return validate_id(value, kind="agent_id")

    @field_validator("profile")
    @classmethod
    def _validate_profile(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in AGENT_PROFILES:
            raise ValueError(f"profile must be one of {AGENT_PROFILES}")
        return normalized

    @field_validator("origin")
    @classmethod
    def _validate_origin(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in AGENT_ORIGINS:
            raise ValueError(f"origin must be one of {AGENT_ORIGINS}")
        return normalized

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in AGENT_STATUSES:
            raise ValueError(f"status must be one of {AGENT_STATUSES}")
        return normalized

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, value: list[str]) -> list[str]:
        # Fail-closed: an unknown permission slug rejects the whole agent.
        return [p.value for p in permission_registry.normalize_many(value)]

    @field_validator("skills", "tools", "integrations")
    @classmethod
    def _clean_assignments(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            entry = str(raw).strip().lower()
            if entry and entry not in cleaned:
                cleaned.append(entry)
        if len(cleaned) > MAX_ASSIGNMENTS:
            raise ValueError(f"an agent cannot declare more than {MAX_ASSIGNMENTS} of one kind")
        return cleaned

    def summary(self) -> dict:
        return self.model_dump(mode="json")


def _system_agents() -> list[AgentDefinition]:
    """Built-in example agents. Exactly one, to validate the architecture."""
    return [
        AgentDefinition(
            id="mustafa",
            name="Mustafa",
            profile="ares",
            description=(
                "Helper agent for A.R.E.S. Specializes in scaffolding and quick "
                "code snippets. This is a helper agent, NOT a third profile."
            ),
            skills=["html-boilerplate", "python-cli-argparse", "fastapi-endpoint"],
            tools=["editor", "terminal"],
            integrations=[],
            permissions=["read", "write", "terminal"],
            origin="system",
            status="enabled",
        ),
    ]


class AgentValidationError(ValueError):
    """A coherence problem with an agent definition, safe to surface."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class AgentFactory:
    """System (in-code) + custom (on-disk) agents, with referential validation."""

    def __init__(self) -> None:
        self._system: dict[str, AgentDefinition] = {a.id: a for a in _system_agents()}

    def _custom_dir(self) -> Path:
        return gcs_data_dir("agents", "custom")

    # -- reads ------------------------------------------------------------
    def list_system(self) -> list[AgentDefinition]:
        return list(self._system.values())

    def list_custom(self) -> list[AgentDefinition]:
        agents: list[AgentDefinition] = []
        directory = self._custom_dir()
        for agent_id in list_document_ids(directory):
            try:
                raw = read_json(document_path(directory, agent_id, kind="agent_id"))
                agent = AgentDefinition.model_validate(raw)
            except (StorageError, ValueError):
                continue
            if agent.origin != "custom":
                agent = agent.model_copy(update={"origin": "custom"})
            agents.append(agent)
        return agents

    def list_all(self) -> list[AgentDefinition]:
        return self.list_system() + self.list_custom()

    def list_for_profile(self, profile: str) -> list[AgentDefinition]:
        target = profile.strip().lower()
        return [a for a in self.list_all() if a.profile == target and a.status == "enabled"]

    def get(self, agent_id: str) -> AgentDefinition | None:
        try:
            safe_id = validate_id(agent_id, kind="agent_id")
        except StorageError:
            return None
        if safe_id in self._system:
            return self._system[safe_id]
        path = document_path(self._custom_dir(), safe_id, kind="agent_id")
        if not path.exists():
            return None
        try:
            raw = read_json(path)
            agent = AgentDefinition.model_validate(raw)
        except (StorageError, ValueError):
            return None
        if agent.origin != "custom":
            agent = agent.model_copy(update={"origin": "custom"})
        return agent

    # -- validation -------------------------------------------------------
    def validate_references(self, agent: AgentDefinition) -> None:
        """Ensure every assigned skill / integration actually exists and is
        coherent with the agent's profile. Fail-closed: any dangling reference
        rejects the whole agent so a saved agent is never broken."""
        for skill_id in agent.skills:
            skill = skill_store.get(skill_id)
            if skill is None:
                raise AgentValidationError("unknown_skill", f"unknown skill: {skill_id}")
            if not skill.supports_profile(agent.profile):
                raise AgentValidationError(
                    "incompatible_skill",
                    f"skill '{skill_id}' is not compatible with profile '{agent.profile}'",
                )
        for integration_id in agent.integrations:
            adapter = integration_hub.get(integration_id)
            if adapter is None:
                raise AgentValidationError(
                    "unknown_integration", f"unknown integration: {integration_id}"
                )
            # An assigned integration must be backed by a held permission.
            if not permission_registry.has(agent.permissions, adapter.permission):
                raise AgentValidationError(
                    "missing_integration_permission",
                    f"integration '{integration_id}' requires the "
                    f"'{adapter.permission.value}' permission",
                )

    # -- writes (custom only) --------------------------------------------
    def save_custom(self, agent: AgentDefinition) -> AgentDefinition:
        if agent.id in self._system:
            raise StorageError(
                "reserved_agent_id", "this id belongs to a protected system agent"
            )
        agent = agent.model_copy(update={"origin": "custom"})
        self.validate_references(agent)
        path = document_path(self._custom_dir(), agent.id, kind="agent_id")
        write_json_atomic_0600(path, agent.model_dump(mode="json"))
        return agent

    def delete_custom(self, agent_id: str) -> bool:
        safe_id = validate_id(agent_id, kind="agent_id")
        if safe_id in self._system:
            raise StorageError("reserved_agent_id", "system agents cannot be deleted")
        return delete_document(document_path(self._custom_dir(), safe_id, kind="agent_id"))


# Singleton shared across the app lifespan.
agent_factory = AgentFactory()
