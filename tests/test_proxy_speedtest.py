"""speedtest.py 单元测试（纯 Python 数据层：无 Qt、无真实网络）。

纪律（AGENTS.md 测试规范）：模块顶层零副作用；HTTP 经
``monkeypatch.setattr(speedtest, "requests", 替身)`` 注入，绝不真连。
"""
import types

import pytest

from modules.proxy_ctrl import speedtest
from modules.proxy_ctrl.speedtest import DEFAULT_TARGET, test_proxy_speed


class _FakeResponse:
    """最小 requests.Response 替身：只需 status_code 与 elapsed。"""

    def __init__(self, status_code, elapsed_ms=50):
        self.status_code = status_code
        self.elapsed = types.SimpleNamespace(
            total_seconds=(lambda ms=elapsed_ms: ms / 1000.0))


def _install_rounds(monkeypatch, rounds):
    """按轮次顺序返回结果。rounds 中每项为 (status, ms) 或 Exception。"""
    queue = list(rounds)
    calls = []

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        if not queue:
            raise AssertionError("实际请求轮次多于预期")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(*item)

    monkeypatch.setattr(speedtest, "requests", types.SimpleNamespace(get=_get))
    return calls


# ------------------------------------------------------------- 空 URL

def test_empty_url_is_considered_usable():
    """与原版 check_proxy_availability 一致：未设代理 = 可用。"""
    result = test_proxy_speed("")
    assert result.ok is True
    assert result.avg_ms == 0
    assert result.samples == []
    assert result.hints == []


def test_whitespace_only_url_is_considered_usable():
    assert test_proxy_speed("   ").ok is True


# --------------------------------------------------------------- 评级

@pytest.mark.parametrize("ms, expected", [
    (0, "✅ 优秀"),
    (99, "✅ 优秀"),
    (100, "👍 良好"),
    (299, "👍 良好"),
    (300, "⚠️ 一般"),
    (499, "⚠️ 一般"),
    (500, "❌ 较差"),
    (5000, "❌ 较差"),
])
def test_rating_thresholds(monkeypatch, ms, expected):
    _install_rounds(monkeypatch, [(204, ms)])
    assert test_proxy_speed("http://192.168.2.9:7890").rating == expected


# ------------------------------------------------------- 只有 2xx 算成功

@pytest.mark.parametrize("status, ok", [
    (200, True), (201, True), (204, True), (299, True),
    (300, False), (301, False), (302, False), (404, False), (500, False),
])
def test_only_2xx_counts_as_success(monkeypatch, status, ok):
    _install_rounds(monkeypatch, [(status, 40)] * 3)
    result = test_proxy_speed("http://192.168.2.9:7890")
    assert result.ok is ok
    assert (result.samples != []) is ok


# ------------------------------------------------------------ 全失败分支

def test_all_rounds_failed_returns_three_hints(monkeypatch):
    _install_rounds(monkeypatch, [OSError("timeout")] * 5)
    result = test_proxy_speed("http://192.168.2.9:7890", rounds=5)
    assert result.ok is False
    assert result.avg_ms == 0
    assert result.samples == []
    assert len(result.hints) == 3
    assert any("端口" in h for h in result.hints)
    assert any("启动" in h for h in result.hints)
    assert any("目标" in h for h in result.hints)


def test_all_rounds_non_2xx_also_fails(monkeypatch):
    _install_rounds(monkeypatch, [(404, 30)] * 3)
    result = test_proxy_speed("http://192.168.2.9:7890", rounds=3)
    assert result.ok is False
    assert len(result.hints) == 3


# --------------------------------------------------------- 平均值语义

def test_average_only_over_successful_samples(monkeypatch):
    """3 成功 2 失败：平均只对 3 个成功样本求平均，samples 也只含它们。"""
    _install_rounds(monkeypatch, [
        (204, 100), OSError("x"), (204, 200), (204, 301), OSError("y"),
    ])
    result = test_proxy_speed("http://192.168.2.9:7890", rounds=5)
    assert result.ok is True
    assert sorted(result.samples) == [100, 200, 301]
    assert result.avg_ms == 200  # (100+200+301)//3 = 200


def test_average_is_floor_division(monkeypatch):
    _install_rounds(monkeypatch, [(204, 100), (204, 101), (204, 102)])
    assert test_proxy_speed("http://192.168.2.9:7890").avg_ms == 101


def test_slow_average_adds_switch_hint(monkeypatch):
    _install_rounds(monkeypatch, [(204, 320)] * 3)
    result = test_proxy_speed("http://192.168.2.9:7890", rounds=3)
    assert result.ok is True
    assert any("更快" in h for h in result.hints)


def test_fast_average_has_no_switch_hint(monkeypatch):
    _install_rounds(monkeypatch, [(204, 90)] * 3)
    result = test_proxy_speed("http://192.168.2.9:7890", rounds=3)
    assert result.hints == []


# ------------------------------------------------------------ 请求契约

def test_uses_expected_requests_kwargs(monkeypatch):
    calls = _install_rounds(monkeypatch, [(204, 40)] * 2)
    test_proxy_speed("http://192.168.2.9:10808", rounds=2,
                     target=DEFAULT_TARGET, connect_timeout=10.0, read_timeout=30.0)
    assert len(calls) == 2
    for url, kwargs in calls:
        assert url == DEFAULT_TARGET
        assert kwargs["proxies"] == {"http": "http://192.168.2.9:10808",
                                     "https": "http://192.168.2.9:10808"}
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == (10.0, 30.0)


def test_result_carries_url(monkeypatch):
    _install_rounds(monkeypatch, [(204, 40)])
    assert test_proxy_speed("http://192.168.2.9:7890").url == "http://192.168.2.9:7890"


def test_rounds_clamps_to_at_least_one(monkeypatch):
    calls = _install_rounds(monkeypatch, [(204, 40)])
    assert test_proxy_speed("http://192.168.2.9:7890", rounds=0).ok is True
    assert len(calls) == 1


# ── 可用性快检（check_proxy_availability）────────────────────────────────
#
# 与 test_proxy_speed 的分工：测速问「有多快」（5 轮 generate_204），
# 快检问「通不通」（1 轮 example.com）。两者目标地址刻意不同 ——
# generate_204 在部分网络不可达，用它做可用性判定会把好代理误报成坏的。

class TestCheckTarget:
    """快检的目标必须是 example.com，不能是 generate_204。"""

    def test_目标不是generate_204(self):
        """回归锁：有人把 CHECK_TARGET 改成 DEFAULT_TARGET 会让国内网络全判不可用。"""
        assert "example.com" in speedtest.CHECK_TARGET
        assert "generate_204" not in speedtest.CHECK_TARGET

    def test_与测速目标是两个不同地址(self):
        assert speedtest.CHECK_TARGET != speedtest.DEFAULT_TARGET

    def test_超时沿用原版curl参数(self):
        """原版是 --connect-timeout 2 --max-time 5。"""
        assert speedtest.CHECK_TIMEOUT == (2.0, 5.0)


class TestCheckProxyAvailability:
    def test_空地址视为可用且不联网(self, monkeypatch):
        monkeypatch.setattr(
            speedtest.requests, "get",
            lambda *a, **k: pytest.fail("空地址不该发起任何请求"))
        ok, detail = speedtest.check_proxy_availability("")
        assert ok is True
        assert "直连" in detail

    def test_纯空白地址同样视为可用(self):
        ok, _ = speedtest.check_proxy_availability("   \t ")
        assert ok is True

    def test_成功时透传代理与超时(self, monkeypatch):
        calls = []

        def _get(url, **kwargs):
            calls.append((url, kwargs))
            return _FakeResponse(200)

        monkeypatch.setattr(speedtest.requests, "get", _get)
        ok, detail = speedtest.check_proxy_availability("http://127.0.0.1:7890")
        assert ok is True
        assert len(calls) == 1
        target, kwargs = calls[0]
        assert target == speedtest.CHECK_TARGET
        assert kwargs["proxies"] == {"http": "http://127.0.0.1:7890",
                                     "https": "http://127.0.0.1:7890"}
        assert kwargs["timeout"] == speedtest.CHECK_TIMEOUT
        assert "200" in detail

    def test_非2xx也算通(self, monkeypatch):
        """代理把请求转到 404 页仍说明链路是通的 —— 判据是「代理能转发」而非「内容对」。"""
        monkeypatch.setattr(speedtest.requests, "get",
                            lambda *a, **k: _FakeResponse(404))
        ok, detail = speedtest.check_proxy_availability("http://p:1")
        assert ok is True
        assert "404" in detail

    def test_网络异常降级为不可用而非抛出(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("Connection refused")

        monkeypatch.setattr(speedtest.requests, "get", _boom)
        ok, detail = speedtest.check_proxy_availability("http://p:1")
        assert ok is False
        assert "Connection refused" in detail

    def test_不因任意异常类型崩掉(self, monkeypatch):
        """代理 URL 畸形时 requests 可能抛各种类型（含 ValueError/KeyError）。"""
        monkeypatch.setattr(speedtest.requests, "get",
                            lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
        ok, _ = speedtest.check_proxy_availability("???")
        assert ok is False

    def test_地址先裁空白再使用(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            speedtest.requests, "get",
            lambda url, **k: (seen.update(url=url), _FakeResponse(200))[1])
        speedtest.check_proxy_availability("  http://p:1  ")
        assert seen["url"] == speedtest.CHECK_TARGET

    def test_文案含代理地址便于定位(self, monkeypatch):
        monkeypatch.setattr(speedtest.requests, "get",
                            lambda *a, **k: _FakeResponse(200))
        _, detail = speedtest.check_proxy_availability("http://10.0.0.9:1080")
        assert "10.0.0.9:1080" in detail
