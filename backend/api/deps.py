"""依赖注入：JWT → RequestContext（tenant_id / user_id / user_role）。

关键：Agent 代码完全不需要处理租户 —— 它只从 State 里读 tenant_id。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import settings
from ..observability.trace import current_trace

bearer = HTTPBearer(auto_error=False)

ROLE_USERS = {
    "doctor": {"name": "王医生", "role": "doctor", "title": "心内科主治医师"},
    "qc_staff": {"name": "李质控", "role": "qc_staff", "title": "质控科质控医师"},
    "patient": {"name": "张伟", "role": "patient", "title": "门诊患者"},
    "admin": {"name": "系统管理员", "role": "admin", "title": "信息科管理员"},
}


@dataclass
class RequestContext:
    tenant_id: str
    user_id: str
    user_role: str
    user_name: str


def create_token(tenant_id: str, user_id: str, role: str, name: str) -> str:
    payload = {
        "tenant_id": tenant_id,
        "sub": user_id,
        "role": role,
        "name": name,
        "exp": int(time.time()) + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_request_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> RequestContext:
    if credentials is None:
        # 内部联调便利：未带 Token 时回落到默认账号（生产环境应直接 401）
        return RequestContext(tenant_id="tnt_renhe", user_id="u_doctor_wang", user_role="doctor", user_name="王医生")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Token 无效：{exc}") from exc

    context = RequestContext(
        tenant_id=payload["tenant_id"],
        user_id=payload["sub"],
        user_role=payload["role"],
        user_name=payload.get("name", ""),
    )
    trace = current_trace()
    if trace is not None:
        trace.tenant_id = context.tenant_id
        trace.user_id = context.user_id
    return context
