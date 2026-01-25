"""请求受理系统 Locust 压测脚本。"""

import os
import uuid
from collections import Counter
from threading import Lock

import requests
from locust import HttpUser, between, events, task

_COUNTER = Counter()
_LOCK = Lock()


def _record_code(code) -> None:
    """记录返回码统计。"""

    with _LOCK:
        _COUNTER[str(code)] += 1


def _print_summary(environment) -> None:
    """输出压测统计汇总。"""

    with _LOCK:
        snapshot = dict(_COUNTER)

    total = sum(snapshot.values())
    if total == 0:
        print("压测结束：未统计到请求数据")
        return

    def _pct(value: int) -> str:
        return f"{(value / total * 100):.2f}%"

    success = snapshot.get("0", 0)
    business_fail = sum(snapshot.get(str(code), 0) for code in (1, 2, 3, 4))
    http_error = snapshot.get("http_error", 0)
    parse_error = snapshot.get("parse_error", 0)
    total_fail = business_fail + http_error + parse_error

    print("压测结果汇总：")
    print(
        "总请求数={total}，成功={success}，失败={fail}，成功率={success_rate}，失败率={fail_rate}".format(
            total=total,
            success=success,
            fail=total_fail,
            success_rate=_pct(success),
            fail_rate=_pct(total_fail),
        )
    )
    print(
        "失败拆分：业务失败(code=1/2/3/4)={biz}，HTTP 异常={http}，解析失败={parse}".format(
            biz=business_fail,
            http=http_error,
            parse=parse_error,
        )
    )

    print("业务码说明：")
    print("code=0 成功，code=1 库存不足，code=2 重复下单，code=3 请求过于频繁，code=4 入队失败")
    print("code=http_error HTTP 状态码异常，code=parse_error 响应解析失败")

    for code in ("0", "1", "2", "3", "4", "http_error", "parse_error"):
        print(f"code={code} 数量={snapshot.get(code, 0)} 占比={_pct(snapshot.get(code, 0))}")

    stats_total = environment.stats.total if environment else None
    if stats_total and stats_total.num_requests > 0:
        def _fmt_ms(value) -> str:
            return f"{int(value)}ms" if value is not None else "N/A"

        def _pct_rt(p: float):
            try:
                return stats_total.get_response_time_percentile(p)
            except Exception:
                return None

        p50 = _pct_rt(0.50)
        p90 = _pct_rt(0.90)
        p95 = _pct_rt(0.95)
        p99 = _pct_rt(0.99)
        p999 = _pct_rt(0.999)

        print("吞吐与延迟：")
        print(
            "总RPS(平均)={avg_rps:.2f}，当前RPS={cur_rps:.2f}，总失败率={fail_rate:.2f}%".format(
                avg_rps=stats_total.total_rps,
                cur_rps=stats_total.current_rps,
                fail_rate=stats_total.fail_ratio * 100,
            )
        )
        print(
            "延迟分位数(ms)：P50={p50}，P90={p90}，P95={p95}，P99={p99}，P99.9={p999}".format(
                p50=_fmt_ms(p50),
                p90=_fmt_ms(p90),
                p95=_fmt_ms(p95),
                p99=_fmt_ms(p99),
                p999=_fmt_ms(p999),
            )
        )
        print(
            "延迟汇总：平均={avg}，最小={min}，最大={max}".format(
                avg=_fmt_ms(stats_total.avg_response_time),
                min=_fmt_ms(stats_total.min_response_time),
                max=_fmt_ms(stats_total.max_response_time),
            )
        )
        print("分位数含义：P90 表示 90% 请求耗时不超过该值")

    if environment:
        order_stats = environment.stats.get("/admission/requests", "POST")
        status_stats = environment.stats.get("/admission/requests/{request_id}", "GET")
        if order_stats and order_stats.num_requests > 0:
            print(
                "接口RPS：POST /admission/requests 平均={avg:.2f} 当前={cur:.2f}".format(
                    avg=order_stats.total_rps,
                    cur=order_stats.current_rps,
                )
            )
        if status_stats and status_stats.num_requests > 0:
            print(
                "接口RPS：GET /admission/requests/{request_id} 平均={avg:.2f} 当前={cur:.2f}".format(
                    avg=status_stats.total_rps,
                    cur=status_stats.current_rps,
                )
            )


def _prepare_stock() -> bool:
    """压测前预热库存。"""

    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    sku_id = os.getenv("SKU_ID", "sku123")
    token = os.getenv("ADMIN_TOKEN", "")
    stock = int(os.getenv("PRELOAD_STOCK", "200000"))

    if token == "":
        print("错误：ADMIN_TOKEN 未设置，无法预热库存")
        return False

    try:
        resp = requests.post(
            f"{base_url}/admin/quota/reset",
            json={"sku_id": sku_id, "stock": stock},
            headers={"X-Admin-Token": token},
            timeout=5,
        )
    except Exception as exc:
        print(f"错误：预热库存失败，{exc}")
        return False

    if resp.status_code != 200:
        print(f"错误：预热库存失败，status={resp.status_code}，body={resp.text}")
        return False

    print(f"预热库存成功：sku_id={sku_id}，stock={stock}")
    return True


@events.test_start.add_listener
def on_test_start(environment, **_kwargs) -> None:
    ok = _prepare_stock()
    if not ok:
        print("错误：预热库存失败，已停止压测")
        if environment.runner:
            environment.runner.quit()
        else:
            raise SystemExit(1)


@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs) -> None:
    _print_summary(environment)


class AdmissionUser(HttpUser):
    """请求受理接口压测用户。"""

    host = os.getenv("BASE_URL", "http://localhost:8000")
    wait_time = between(0.01, 0.05)
    sku_id = os.getenv("SKU_ID", "sku123")
    last_request_id = None

    @task(5)
    def seckill_order(self) -> None:
        payload = {
            "user_id": str(uuid.uuid4()),
            "sku_id": self.sku_id,
        }
        with self.client.post("/admission/requests", json=payload, catch_response=True) as resp:
            if resp.status_code not in (200, 202):
                resp.failure("HTTP 状态码异常")
                _record_code("http_error")
                return

            try:
                data = resp.json()
            except Exception:
                resp.failure("响应解析失败")
                _record_code("parse_error")
                return

            code = data.get("code")
            self.last_request_id = data.get("request_id")

            if code == 0:
                resp.success()
            else:
                resp.failure(f"业务失败 code={code}")
            _record_code(code)

    @task(1)
    def seckill_status(self) -> None:
        if not self.last_request_id:
            return
        with self.client.get(
            f"/admission/requests/{self.last_request_id}",
            catch_response=True,
            name="/admission/requests/{request_id}",
        ) as resp:
            if resp.status_code != 200:
                resp.failure("HTTP 状态码异常")
