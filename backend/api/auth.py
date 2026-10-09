"""认证接口 —— 支持「角色一键登录」，生产环境可对接院内统一身份认证（SSO）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..infra.db import db
from .deps import ROLE_USERS, RequestContext, create_token, get_request_context

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    role: str = "doctor"
    tenant_id: str = "tnt_renhe"


@router.post("/login")
async def role_login(body: LoginRequest) -> dict:
    user = ROLE_USERS.get(body.role, ROLE_USERS["doctor"])
    user_id = f"u_{body.role}"
    token = create_token(body.tenant_id, user_id, user["role"], user["name"])
    return {
        "token": token,
        "token_type": "Bearer",
        "expires_in": 720 * 60,
        "user": {
            "user_id": user_id,
            "name": user["name"],
            "role": user["role"],
            "title": user["title"],
            "tenant_id": body.tenant_id,
        },
    }


@router.get("/tenants")
async def tenants() -> dict:
    rows = await db.fetch_all("SELECT tenant_id, name, hospital_level FROM tenant ORDER BY tenant_id")
    return {"items": rows, "roles": [{"role": k, **v} for k, v in ROLE_USERS.items()]}


@router.get("/me")
async def me(ctx: RequestContext = Depends(get_request_context)) -> dict:
    return {
        "user_id": ctx.user_id,
        "name": ctx.user_name,
        "role": ctx.user_role,
        "tenant_id": ctx.tenant_id,
    }
