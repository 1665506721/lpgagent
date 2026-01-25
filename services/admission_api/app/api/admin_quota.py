"""管理侧配额预热与查询接口。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from redis.exceptions import RedisError

from app.core.security import require_admin_token
from app.infra.redis_client import get_redis

router = APIRouter(prefix="/admin/quota", tags=["admin"], dependencies=[Depends(require_admin_token)])


class QuotaRequest(BaseModel):
    """配额写入请求体。"""

    model_config = ConfigDict(populate_by_name=True)

    resource_id: str = Field(
        ...,
        min_length=1,
        description="资源 ID",
        validation_alias=AliasChoices("resource_id", "sku_id"),
    )
    stock: int = Field(..., ge=0, description="配额数量")


@router.post("/load")
def load_quota(payload: QuotaRequest) -> dict:
    """预热/设置配额。"""

    try:
        redis_client = get_redis()
        key = f"stock:{payload.resource_id}"
        redis_client.set(key, payload.stock)
        return {"resource_id": payload.resource_id, "stock": payload.stock}
    except RedisError:
        raise HTTPException(status_code=503, detail="Redis 不可用")


@router.get("/{resource_id}")
def get_quota(resource_id: str) -> dict:
    """查询配额。"""

    try:
        redis_client = get_redis()
        value = redis_client.get(f"stock:{resource_id}")
        stock = int(value) if value is not None else 0
        return {"resource_id": resource_id, "stock": stock}
    except RedisError:
        raise HTTPException(status_code=503, detail="Redis 不可用")


@router.post("/reset")
def reset_quota(payload: QuotaRequest) -> dict:
    """重置配额并清理幂等 Key。"""

    try:
        redis_client = get_redis()
        redis_client.set(f"stock:{payload.resource_id}", payload.stock)

        pattern = f"order_once:{payload.resource_id}:*"
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=500)
            if keys:
                deleted += redis_client.delete(*keys)
            if cursor == 0:
                break

        return {
            "resource_id": payload.resource_id,
            "stock": payload.stock,
            "deleted_order_once_keys": deleted,
        }
    except RedisError:
        raise HTTPException(status_code=503, detail="Redis 不可用")
