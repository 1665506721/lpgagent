"""请求受理入口与状态查询接口。"""

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.infra.kafka_producer import send_order_create
from app.infra.metrics import ADMISSION_REQUESTS_TOTAL, KAFKA_PRODUCE_FAIL_TOTAL
from app.infra.redis_client import get_redis
from app.infra.seckill_lua import execute_seckill

router = APIRouter(prefix="/admission", tags=["admission"])


class AdmissionRequest(BaseModel):
    """请求受理请求体。"""

    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(..., min_length=1, description="用户 ID")
    sku_id: str = Field(
        ...,
        min_length=1,
        description="资源 ID",
        validation_alias=AliasChoices("sku_id", "resource_id"),
    )
    request_id: Optional[str] = Field(default=None, min_length=1, description="请求 ID")


@router.post("/requests")
def create_request(payload: AdmissionRequest) -> JSONResponse:
    """执行请求受理原子逻辑。"""

    request_id = payload.request_id or str(uuid4())
    redis_client = get_redis()
    result = execute_seckill(
        redis_client,
        sku_id=payload.sku_id,
        user_id=payload.user_id,
        request_id=request_id,
    )

    if result["code"] == 0:
        sent = send_order_create(
            request_id=request_id,
            user_id=payload.user_id,
            sku_id=payload.sku_id,
        )
        if not sent:
            redis_client.set(f"req_status:{request_id}", "FAILED", ex=3600)
            result["code"] = 4
            result["message"] = "已受理但入队失败"
            KAFKA_PRODUCE_FAIL_TOTAL.inc()

    ADMISSION_REQUESTS_TOTAL.labels(code=str(result["code"])).inc()

    status_code = 202 if result["code"] == 0 else 200
    return JSONResponse(content=result, status_code=status_code)


@router.get("/requests/{request_id}")
def get_request_status(request_id: str) -> dict:
    """查询请求状态。"""

    redis_client = get_redis()
    status = redis_client.get(f"req_status:{request_id}")
    return {
        "request_id": request_id,
        "status": status if status else "NOT_FOUND",
    }
