"""健康检查接口。"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    """用于容器健康检查的简单接口。"""

    return {"status": "ok"}
