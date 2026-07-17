"""
Context Builder — GERAM Core System.

The ONE place that assembles the context handed to any provider. Every caller
(orchestrator, future providers) goes through here so sanitization can never be
forgotten in one code path and remembered in another.

It delivers exactly, and only:

    Profile -> Agent -> Authorized Skills -> Tools
            -> Sanitized Integrations -> Memory State -> Permissions

It NEVER includes tokens, credentials, private paths, sensitive information, or
permanent memory when that tier is disabled. It is provider-agnostic on
purpose: any future provider can consume the same neutral, sanitized bundle.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.gcs.agent_factory import AgentDefinition, agent_factory
from app.core.gcs.integrations import integration_hub
from app.core.gcs.memory import memory_manager
from app.core.gcs.permissions import permission_registry
from app.core.gcs.skills import Skill, skill_store

# Only these two permanent profiles exist. This is enforced, not assumed.
PROFILES = ("iris", "ares")


@dataclass(frozen=True)
class BuiltContext:
    """A sanitized, provider-neutral context bundle."""

    profile: str
    agent: dict | None
    permissions: list[str]
    skills: list[dict]
    knowledge: list[dict]
    tools: list[str]
    integrations: list[dict]
    memory: dict

    def as_dict(self) -> dict:
        return {
            "profile": self.profile,
            "agent": self.agent,
            "permissions": self.permissions,
            "skills": self.skills,
            "knowledge": self.knowledge,
            "tools": self.tools,
            "integrations": self.integrations,
            "memory": self.memory,
        }


class ContextBuilderError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ContextBuilder:
    """Assembles the single sanitized context bundle."""

    def _authorized_skills(self, agent: AgentDefinition | None, profile: str) -> list[Skill]:
        """Resolve an agent's assigned skills to real, enabled, compatible ones.

        With no agent, the profile gets no ambient skills — least privilege.
        Dangling / disabled / incompatible references are silently dropped so a
        stale assignment never leaks a wrong or broken skill into context.
        """
        if agent is None:
            return []
        resolved: list[Skill] = []
        for skill_id in agent.skills:
            skill = skill_store.get(skill_id)
            if skill is None or skill.status != "enabled":
                continue
            if not skill.supports_profile(profile):
                continue
            resolved.append(skill)
        return resolved

    def _sanitized_integrations(self, granted: list[str]) -> list[dict]:
        """Sanitized integration list, annotated with the authorization tier.

        available -> connected -> authorized. ``authorized`` is only True when
        the integration is connected AND the effective permission is held.
        Never contains a token or secret value.
        """
        result: list[dict] = []
        for status in integration_hub.list_integrations():
            permission = status["permission"]
            connected = status["state"] == "connected"
            authorized = connected and permission_registry.has(granted, permission)
            result.append({**status, "authorized": authorized})
        return result

    def build(self, profile: str, agent_id: str | None = None) -> BuiltContext:
        target = (profile or "").strip().lower()
        if target not in PROFILES:
            raise ContextBuilderError("invalid_profile", "profile must be iris or ares")

        agent: AgentDefinition | None = None
        if agent_id:
            agent = agent_factory.get(agent_id)
            if agent is None:
                raise ContextBuilderError("unknown_agent", f"unknown agent: {agent_id}")
            if agent.profile != target:
                # An agent belongs to exactly one profile; it can only be used
                # from the profile that owns it.
                raise ContextBuilderError(
                    "profile_mismatch",
                    f"agent '{agent.id}' belongs to profile '{agent.profile}', not '{target}'",
                )
            if agent.status != "enabled":
                raise ContextBuilderError("agent_disabled", f"agent '{agent.id}' is disabled")

        # Effective permissions come solely from the agent. A bare profile with
        # no agent holds nothing (least privilege), so nothing sensitive leaks.
        granted = list(agent.permissions) if agent else []

        skills = self._authorized_skills(agent, target)

        return BuiltContext(
            profile=target,
            agent=agent.summary() if agent else None,
            permissions=granted,
            skills=[s.summary() for s in skills],
            knowledge=[{"id": s.id, "name": s.name, "body": s.body} for s in skills],
            tools=list(agent.tools) if agent else [],
            integrations=self._sanitized_integrations(granted),
            memory=memory_manager.memory_state(granted),
        )


# Singleton shared across the app lifespan.
context_builder = ContextBuilder()
