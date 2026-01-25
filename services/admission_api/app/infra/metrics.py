"""Prometheus 指标暴露。"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

router = APIRouter()

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "HTTP 请求计数示例，用于演示指标采集。",
)

ADMISSION_REQUESTS_TOTAL = Counter(
    "admission_requests_total",
    "请求受理计数。",
    ["code"],
)

KAFKA_PRODUCE_FAIL_TOTAL = Counter(
    "kafka_produce_fail_total",
    "Kafka 发送失败计数。",
)


@router.get("/metrics")
def metrics() -> Response:
    """Prometheus 指标出口。"""

    HTTP_REQUESTS_TOTAL.inc()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
