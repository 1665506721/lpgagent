"""FastAPI 应用入口。"""

import logging

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.admin_quota import router as admin_quota_router
from app.api.admission import router as admission_router
from app.api.health import router as health_router
from app.core.config import settings
from app.core.logging import init_logging
from app.infra.metrics import router as metrics_router


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""

    init_logging()

    if settings.ADMIN_TOKEN == "":
        raise RuntimeError("ADMIN_TOKEN 未配置，请设置环境变量 ADMIN_TOKEN")
    if settings.KAFKA_BOOTSTRAP_SERVERS == "":
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS 未配置，请设置环境变量 KAFKA_BOOTSTRAP_SERVERS")

    app = FastAPI(title=settings.APP_NAME)
    app.include_router(admin_quota_router)
    app.include_router(health_router)
    app.include_router(admission_router)
    app.include_router(metrics_router)

    @app.exception_handler(Exception)
    def handle_exception(_: Request, exc: Exception) -> JSONResponse:
        logging.exception("未处理异常", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.LOG_LEVEL.lower(),
        reload=False,
    )
