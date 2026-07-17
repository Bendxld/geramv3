"""
GERAM Core System (GCS) — the local-first AI Operating Environment core.

This subpackage is the *evolution* of the existing Core, not a parallel
implementation. It reuses the same conventions used everywhere else in
`app/core/`:

  * Pydantic models with ``extra="forbid"`` for every contract.
  * Fail-safe loaders that degrade to validated defaults instead of raising
    inside a request path (a broken file never takes GERAM down).
  * Atomic ``0600`` writes for anything persisted to disk.
  * User content persisted OUTSIDE the source tree, under
    ``settings.LOCAL_DATA_DIR`` (``~/.local/share/geram-core-os``).

It provides the six pillars of the AI Operating Environment:

  * :mod:`app.core.gcs.permissions`     — central Permission Registry.
  * :mod:`app.core.gcs.skills`          — versioned, portable Skill System.
  * :mod:`app.core.gcs.skill_retriever` — fully-local Skill Retriever.
  * :mod:`app.core.gcs.integrations`    — Integration Hub (adapters + state).
  * :mod:`app.core.gcs.agent_factory`   — user-owned Agent Factory.
  * :mod:`app.core.gcs.context_builder` — single sanitized Context Builder.
  * :mod:`app.core.gcs.memory`          — session vs permanent memory state.

Design principle enforced throughout: **the user controls the AI, the AI
never controls GERAM.** Existence of an integration never grants access — a
permission must always be verified. Everything works fully offline; GERAM
boots with zero API keys configured.
"""
