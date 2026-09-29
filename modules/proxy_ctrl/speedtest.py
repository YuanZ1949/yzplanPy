"""代理测速器：逐轮经代理请求 generate_204，统计平均延迟并评级。

移植自 toggle_proxy「全能代理管理器 v3.2」的 modules/speed_test.ps1。
纯 Python 数据层，不 import Qt，可在无 QApplication 环境下完整单测。

与原版的差异（有意为之）：原版格式串会残留一个 ``N``（``%d`` 之外的
printf bug），不复刻；成功判定沿用 ``^2`` 前缀即 2xx。

测试注入点：``requests`` 模块级名，替换为 SimpleNamespace(get=...) 即可。
"""
from dataclasses import dataclass, field

import requests

from .scanner import DEFAULT_TARGET

#: 平均延迟 ≥ 该值即提示切换更快节点（原版阈值）
SLOW_AVG_MS = 300

#: 全失败时给用户的 3 条排查建议
FAILURE_HINTS = (
    "确认代理地址与端口是否正确（形如 192.168.2.10:7890）",
    "确认代理程序已启动并正在监听该端口",
    "确认测速目标地址在当前网络下可访问",
)
SLOW_HINT = "该代理响应较慢，建议切换到更快的代理或更近的节点"


@dataclass
class SpeedResult:
    """一次测速的汇总结果。``samples`` 只含成功轮次的耗时（毫秒）。"""

    url: str
    ok: bool
    avg_ms: int
    samples: list = field(default_factory=list)
    rating: str = ""
    hints: list = field(default_factory=list)


def rate_speed(avg_ms: int) -> str:
    """四档评级（与原版一致）：<100 优秀 / <300 良好 / <500 一般 / 否则较差。"""
    if avg_ms < 100:
        return "✅ 优秀"
    if avg_ms < 300:
        return "👍 良好"
    if avg_ms < 500:
        return "⚠️ 一般"
    return "❌ 较差"


def test_proxy_speed(url, *, rounds=5, target=DEFAULT_TARGET,
                     connect_timeout=10.0, read_timeout=30.0) -> SpeedResult:
    """经 ``url`` 代理连打 ``target`` ``rounds`` 轮，返回平均延迟与评级。

    - **仅 2xx 计入成功**，``avg`` 只对成功样本求平均（整除向下取整）
    - 全轮失败 → ``ok=False``、``avg_ms=0``、``hints`` 给 3 条排查建议
    - 空 url 视为可用（沿用原版 ``check_proxy_availability`` 语义）
    """
    url = (url or "").strip()
    if not url:
        # 未设代理 = 无需代理即可用。评级标「未测速」而非伪造一个优秀值。
        return SpeedResult(url=url, ok=True, avg_ms=0, rating="— 未测速")

    rounds = max(1, int(rounds))
    proxies = {"http": url, "https": url}
    timeout = (connect_timeout, read_timeout)
    samples: list = []
    for _ in range(rounds):
        try:
            resp = requests.get(target, proxies=proxies, allow_redirects=False,
                                timeout=timeout)
        except Exception:
            continue  # 单轮失败不影响其余轮次
        status = getattr(resp, "status_code", 0)
        if not isinstance(status, int) or status // 100 != 2:
            continue
        elapsed = getattr(getattr(resp, "elapsed", None), "total_seconds", None)
        try:
            samples.append(int(round(elapsed() * 1000)) if callable(elapsed) else 0)
        except Exception:
            continue

    if not samples:
        return SpeedResult(url=url, ok=False, avg_ms=0, rating=rate_speed(0),
                           hints=list(FAILURE_HINTS))
    avg_ms = sum(samples) // len(samples)
    hints = [SLOW_HINT] if avg_ms >= SLOW_AVG_MS else []
    return SpeedResult(url=url, ok=True, avg_ms=avg_ms, samples=samples,
                       rating=rate_speed(avg_ms), hints=hints)


# 规格要求公开名为 test_proxy_speed（与原版 test_port_speed 对齐）。该名字以
# "test_" 开头，任何 `from ... import test_proxy_speed` 的模块都会被 pytest
# 当成测试函数收集并报 "fixture 'url' not found"。标 __test__ = False 关掉
# 收集，让下游可以放心直接导入。
test_proxy_speed.__test__ = False
