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
