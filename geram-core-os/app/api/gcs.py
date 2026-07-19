"""
GERAM Core System Router — the AI Operating Environment API surface.

One cohesive, localhost-only router exposing the six pillars:

    GET    /api/gcs/permissions              -> Permission Registry catalog
    GET    /api/gcs/skills                    -> Skill catalog (system + custom)
    GET    /api/gcs/skills/{id}               -> one skill (with inert body)
    POST   /api/gcs/skills                    -> create/update a CUSTOM skill
    DELETE /api/gcs/skills/{id}               -> delete a custom skill
    POST   /api/gcs/skills/retrieve           -> LOCAL Skill Retriever
    GET    /api/gcs/integrations              -> sanitized Integration Hub
    POST   /api/gcs/integrations/{id}/invoke  -> permission-gated action
    GET    /api/gcs/agents                    -> Agent Factory catalog
    GET    /api/gcs/agents/{id}               -> one agent
    POST   /api/gcs/agents                    -> create/update a CUSTOM agent
    DELETE /api/gcs/agents/{id}               -> delete a custom agent
    POST   /api/gcs/context                   -> Context Builder bundle

All reads and writes are localhost-only; writes additionally require a local
browser origin, matching the existing settings/config endpoints. Local skills,
agents, memory, and Obsidian work offline. Network integrations make a real
request only after connection, permission, and approval checks succeed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.core.gcs.agent_factory import AgentDefinition, AgentValidationError, agent_factory
from app.core.gcs.context_builder import ContextBuilderError, context_builder
from app.core.gcs.integrations import integration_hub
from app.core.gcs.permissions import permission_registry
from app.core.gcs.skill_retriever import skill_retriever
from app.core.gcs.skills import Skill, skill_store
from app.core.gcs.storage import StorageError
from app.core.agent_roster import agent_roster_store
from app.core.security import require_local_origin, require_localhost

router = APIRouter(
    prefix="/api/gcs",
    tags=["gcs"],
    dependencies=[Depends(require_localhost)],
)


# ----------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------
class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    profile: str = "any"
    limit: int = Field(default=5, ge=1, le=20)


class InvokeIntegrationRequest(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)
    # Authorization is derived from the agent's granted permissions — the caller
    # cannot pass arbitrary grants. No agent => no permissions => denied.
    agent_id: str | None = None
    approved: bool = False


class ContextRequest(BaseModel):
    profile: str
    agent_id: str | None = None


def _validation_error(error: ValidationError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "invalid_document", "message": "the submitted document is invalid"},
    )


# ----------------------------------------------------------------------
# Permission Registry
# ----------------------------------------------------------------------
@router.get("/permissions")
async def list_permissions():
    return {
        "permissions": [
            {
                "permission": spec.permission.value,
                "label": spec.label,
                "description": spec.description,
                "sensitive": spec.sensitive,
            }
            for spec in permission_registry.catalog()
        ]
    }


# ----------------------------------------------------------------------
# Skill System
# ----------------------------------------------------------------------
@router.get("/skills")
async def list_skills():
    return {"skills": [s.summary() for s in skill_store.list_all()]}


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str):
    skill = skill_store.get(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail={"code": "skill_not_found"})
    return skill.model_dump(mode="json")


@router.post("/skills", dependencies=[Depends(require_local_origin)])
async def save_skill(payload: dict):
    try:
        skill = Skill.model_validate(payload)
    except ValidationError as error:
        raise _validation_error(error) from None
    try:
        saved = skill_store.save_custom(skill)
    except StorageError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from None
    return {"status": "ok", "skill": saved.summary()}


@router.delete("/skills/{skill_id}", dependencies=[Depends(require_local_origin)])
async def delete_skill(skill_id: str):
    try:
        removed = skill_store.delete_custom(skill_id)
    except StorageError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from None
    if not removed:
        raise HTTPException(status_code=404, detail={"code": "skill_not_found"})
    return {"status": "deleted", "id": skill_id}


@router.post("/skills/retrieve")
async def retrieve_skill(payload: RetrieveRequest):
    result = skill_retriever.retrieve(
        payload.query, profile=payload.profile, limit=payload.limit
    )
    return result.as_dict()


# ----------------------------------------------------------------------
# Integration Hub
# ----------------------------------------------------------------------
@router.get("/integrations")
async def list_integrations():
    return {"integrations": integration_hub.list_integrations()}


@router.post("/integrations/{integration_id}/invoke", dependencies=[Depends(require_local_origin)])
async def invoke_integration(integration_id: str, payload: InvokeIntegrationRequest):
    # Derive granted permissions from the named agent — never from the request.
    granted: list[str] = []
    if payload.agent_id:
        agent = agent_factory.get(payload.agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail={"code": "agent_not_found"})
        if agent.status != "enabled" or not agent_roster_store.is_enabled(
            f"definition:{agent.id}"
        ):
            raise HTTPException(status_code=409, detail={"code": "agent_disabled"})
        granted = list(agent.permissions)
    result = integration_hub.invoke(
        integration_id, payload.action, payload.params, granted=granted, approved=payload.approved
    )
    return result.as_dict()


# ----------------------------------------------------------------------
# Agent Factory
# ----------------------------------------------------------------------
@router.get("/agents")
async def list_agents():
    return {"agents": [a.summary() for a in agent_factory.list_all()]}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = agent_factory.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "agent_not_found"})
    return agent.summary()


@router.post("/agents", dependencies=[Depends(require_local_origin)])
async def save_agent(payload: dict):
    try:
        agent = AgentDefinition.model_validate(payload)
    except ValidationError as error:
        raise _validation_error(error) from None
    try:
        saved = agent_factory.save_custom(agent)
    except AgentValidationError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": str(error)}) from None
    except StorageError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from None
    return {"status": "ok", "agent": saved.summary()}


@router.delete("/agents/{agent_id}", dependencies=[Depends(require_local_origin)])
async def delete_agent(agent_id: str):
    try:
        removed = agent_factory.delete_custom(agent_id)
    except StorageError as error:
        raise HTTPException(status_code=409, detail={"code": error.code, "message": str(error)}) from None
    if not removed:
        raise HTTPException(status_code=404, detail={"code": "agent_not_found"})
    return {"status": "deleted", "id": agent_id}


# ----------------------------------------------------------------------
# Context Builder
# ----------------------------------------------------------------------
@router.post("/context")
async def build_context(payload: ContextRequest):
    try:
        context = context_builder.build(payload.profile, payload.agent_id)
    except ContextBuilderError as error:
        status = 404 if error.code in {"unknown_agent"} else 422
        raise HTTPException(status_code=status, detail={"code": error.code, "message": str(error)}) from None
    return context.as_dict()
