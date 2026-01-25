"""管理接口最小鉴权。"""

from fastapi import Header, HTTPException

from app.core.config import settings


def require_admin_token(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
) -> None:
    """校验管理接口 Token。"""

    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="未授权")
