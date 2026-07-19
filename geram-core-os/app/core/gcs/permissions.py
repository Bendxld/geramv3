"""
Permission Registry — GERAM Core System.

A single, central catalog of every capability an agent can be granted. This is
the authority that makes GERAM's core promise enforceable:

    The existence of a tool or integration NEVER grants access.
    A permission must always be verified, and sensitive operations return
    ``Approval Required`` instead of executing automatically.

Everything here is fail-closed: an unknown permission, a missing grant, or a
malformed request all resolve to "denied", never to "allowed".

The catalog is intentionally small and stable — new integrations map onto the
existing ``INTEGRATION:<id>`` convention rather than inventing bespoke
permission code paths, so Developer Packs can extend the system later without
touching the Core.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Permission(str, Enum):
    """Canonical permission slugs. String-valued so they serialize cleanly."""

    READ = "read"                       # read workspace files
    WRITE = "write"                     # create / modify workspace files
    TERMINAL = "terminal"               # run shell commands
    TEST_RUNNER = "test_runner"         # run the isolated test runner
    INTERNET = "internet"               # any outbound network access
    SPOTIFY = "spotify"                 # Spotify integration actions
    NOTION = "notion"                   # Notion integration actions
    TELEGRAM = "telegram"               # Telegram messages
    SUPABASE = "supabase"               # Supabase table access
    CALENDAR = "calendar"               # Google Calendar events
    OBSIDIAN = "obsidian"               # Local Obsidian vault notes
    SESSION_MEMORY = "session_memory"   # ephemeral, per-session memory
    PERMANENT_MEMORY = "permanent_memory"  # durable memory across sessions


@dataclass(frozen=True)
class PermissionSpec:
    """Static metadata describing one permission in the registry."""

    permission: Permission
    label: str
    description: str
    # Sensitive permissions gate operations that mutate state, spend money,
    # touch the network, or persist beyond the session. Granting one is not
    # enough to run automatically — the operation must be *approved*.
    sensitive: bool


# The registry itself. Ordered for stable, human-readable API output.
_REGISTRY: dict[Permission, PermissionSpec] = {
    Permission.READ: PermissionSpec(
        Permission.READ, "Lectura", "Read files inside the isolated workspace.", False
    ),
    Permission.WRITE: PermissionSpec(
        Permission.WRITE, "Escritura", "Create or modify workspace files.", True
    ),
    Permission.TERMINAL: PermissionSpec(
        Permission.TERMINAL, "Terminal", "Execute shell commands in the sandbox.", True
    ),
    Permission.TEST_RUNNER: PermissionSpec(
        Permission.TEST_RUNNER, "Test Runner", "Run the isolated test runner.", True
    ),
    Permission.INTERNET: PermissionSpec(
        Permission.INTERNET, "Internet", "Access the network / external services.", True
    ),
    Permission.SPOTIFY: PermissionSpec(
        Permission.SPOTIFY, "Spotify", "Control Spotify playback via the hub.", True
    ),
    Permission.NOTION: PermissionSpec(
        Permission.NOTION, "Notion", "Create Notion pages via the hub.", True
    ),
    Permission.TELEGRAM: PermissionSpec(
        Permission.TELEGRAM, "Telegram", "Send messages to an allowed Telegram chat.", True
    ),
    Permission.SUPABASE: PermissionSpec(
        Permission.SUPABASE, "Supabase", "Read or insert bounded Supabase rows.", True
    ),
    Permission.CALENDAR: PermissionSpec(
        Permission.CALENDAR, "Calendar", "Read or create Google Calendar events.", True
    ),
    Permission.OBSIDIAN: PermissionSpec(
        Permission.OBSIDIAN, "Obsidian", "Read or write Markdown notes in the configured vault.", True
    ),
    Permission.SESSION_MEMORY: PermissionSpec(
        Permission.SESSION_MEMORY, "Session memory", "Use ephemeral session memory.", False
    ),
    Permission.PERMANENT_MEMORY: PermissionSpec(
        Permission.PERMANENT_MEMORY,
        "Permanent memory",
        "Persist durable memory across sessions.",
        True,
    ),
}


class PermissionRegistry:
    """Read-only authority over the permission catalog and grant checks."""

    def catalog(self) -> list[PermissionSpec]:
        """Every known permission, in a stable order."""
        return list(_REGISTRY.values())

    def is_known(self, value: str) -> bool:
        try:
            self.normalize(value)
            return True
        except ValueError:
            return False

    def normalize(self, value: str) -> Permission:
        """Coerce a slug to a :class:`Permission`; raise on anything unknown."""
        try:
            return Permission(str(value).strip().lower())
        except ValueError as error:
            raise ValueError(f"unknown permission: {value!r}") from error

    def normalize_many(self, values: list[str]) -> list[Permission]:
        """Validate a list of slugs, de-duplicated, order preserved. Fail-closed:
        a single unknown slug rejects the whole set."""
        seen: list[Permission] = []
        for value in values:
            permission = self.normalize(value)
            if permission not in seen:
                seen.append(permission)
        return seen

    def is_sensitive(self, permission: Permission) -> bool:
        return _REGISTRY[permission].sensitive

    def spec(self, permission: Permission) -> PermissionSpec:
        return _REGISTRY[permission]

    def has(self, granted: list[str] | list[Permission], required: str | Permission) -> bool:
        """Fail-closed grant check: is ``required`` present in ``granted``?

        Any malformed input (unknown required permission, junk in the grant
        list) resolves to ``False`` — never to access.
        """
        try:
            needed = required if isinstance(required, Permission) else self.normalize(required)
        except ValueError:
            return False
        for item in granted:
            try:
                held = item if isinstance(item, Permission) else self.normalize(item)
            except ValueError:
                continue
            if held == needed:
                return True
        return False

    def decide(
        self, granted: list[str] | list[Permission], required: str | Permission
    ) -> "PermissionDecision":
        """Resolve a capability request to allow / deny / approval-required.

        The three-state outcome is what enforces the "sensitive operations do
        not run automatically" rule: even a fully-granted sensitive permission
        yields ``approval_required`` rather than ``allowed``.
        """
        try:
            needed = required if isinstance(required, Permission) else self.normalize(required)
        except ValueError:
            return PermissionDecision("denied", None, "unknown_permission")
        if not self.has(granted, needed):
            return PermissionDecision("denied", needed, "not_granted")
        if self.is_sensitive(needed):
            return PermissionDecision("approval_required", needed, "sensitive_operation")
        return PermissionDecision("allowed", needed, "granted")


@dataclass(frozen=True)
class PermissionDecision:
    """Outcome of :meth:`PermissionRegistry.decide`."""

    outcome: str  # "allowed" | "approval_required" | "denied"
    permission: Permission | None
    reason: str

    @property
    def approval_required(self) -> bool:
        return self.outcome == "approval_required"

    @property
    def allowed(self) -> bool:
        return self.outcome == "allowed"

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "permission": self.permission.value if self.permission else None,
            "reason": self.reason,
        }


# Singleton shared across the app lifespan.
permission_registry = PermissionRegistry()
