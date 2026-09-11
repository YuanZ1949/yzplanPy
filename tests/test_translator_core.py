"""translator_core 测试：解析、缓存、失败、速率限制（全部离线，不触网）。"""
import json

import pytest

from modules.translator import translator_core as tc


@pytest.fixture(autouse=True)
def _clean_state():
    tc._cache.clear()
    tc._last_call = 0.0
    yield
    tc._cache.clear()
    tc._last_call = 0.0


class _Resp:
    """模拟 urllib 响应对象（context manager）。"""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def _canned(text="你好"):
    return json.dumps([[text, "Hello", None, None, 10], None, "en"]).encode("utf-8")


def _patch_open(monkeypatch, payload=None, urls=None):
    payload = _canned() if payload is None else payload
    urls = [] if urls is None else urls

    def _fake_open(url, timeout=None):
        urls.append(url)
        return _Resp(payload)

    monkeypatch.setattr(tc, "_http_open", _fake_open)
    return urls


# ── 解析 ─────────────────────────────────────────────────────────

def test_translate_parses_canned_response(monkeypatch):
    urls = _patch_open(monkeypatch)
    result = tc.translate_text("Hello", dst_lang="zh-CN")
    assert result == "你好"
    assert len(urls) == 1
    assert "sl=auto" in urls[0]
    assert "tl=zh-CN" in urls[0]
    assert "q=Hello" in urls[0]


def test_translate_joins_multiple_chunks(monkeypatch):
    payload = json.dumps([
        [["你", "You", None, None, 10], ["好", "good", None, None, 10]],
        None, "en",
    ]).encode("utf-8")
    _patch_open(monkeypatch, payload=payload)
    assert tc.translate_text("你好") == "你好"


def test_translate_empty_text_returns_empty(monkeypatch):
    urls = _patch_open(monkeypatch)
    assert tc.translate_text("") == ""
    assert urls == []


# ── 语言代码规范化 ───────────────────────────────────────────────

def test_zh_maps_to_zh_cn(monkeypatch):
    urls = _patch_open(monkeypatch)
    tc.translate_text("Hello", dst_lang="zh")
    assert "tl=zh-CN" in urls[0]


def test_unknown_dst_falls_back_to_zh_cn(monkeypatch):
    urls = _patch_open(monkeypatch)
    tc.translate_text("Hello", dst_lang="xx")
    assert "tl=zh-CN" in urls[0]


def test_unknown_src_falls_back_to_auto(monkeypatch):
    urls = _patch_open(monkeypatch)
    tc.translate_text("Hello", src_lang="xx")
    assert "sl=auto" in urls[0]


def test_languages_list_ordered():
    codes = [code for _name, code in tc.LANGUAGES]
    assert codes == ["auto", "zh", "en", "ja", "ko", "fr", "de", "es"]


# ── 缓存 ─────────────────────────────────────────────────────────

def test_cache_second_call_no_network(monkeypatch):
    urls = _patch_open(monkeypatch)
    assert tc.translate_text("Hello", dst_lang="zh-CN") == "你好"
    assert tc.translate_text("Hello", dst_lang="zh-CN") == "你好"
    assert len(urls) == 1


def test_cache_evicts_over_cap(monkeypatch):
    urls = _patch_open(monkeypatch)
    for i in range(tc._CACHE_MAX + 10):
        tc.translate_text(f"text{i}")
    assert len(tc._cache) <= tc._CACHE_MAX
    assert len(urls) == tc._CACHE_MAX + 10


# ── 失败路径 ─────────────────────────────────────────────────────

def test_failure_returns_error_prefix(monkeypatch):
    def _boom(url, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(tc, "_http_open", _boom)
    result = tc.translate_text("Hello")
    assert result.startswith("[翻译失败:")


def test_failure_does_not_cache(monkeypatch):
    def _boom(url, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(tc, "_http_open", _boom)
    tc.translate_text("Hello")
    assert tc._cache == {}


# ── 速率限制 ─────────────────────────────────────────────────────

def test_throttle_cache_hit_no_second_call(monkeypatch):
    """两次快速调用（首次缓存未命中）→ 仅一次 _http_open 调用。"""
    urls = _patch_open(monkeypatch)
    tc.translate_text("Hello", dst_lang="zh-CN")
    tc.translate_text("Hello", dst_lang="zh-CN")
    assert len(urls) == 1


def test_throttle_sleeps_on_rapid_cache_miss(monkeypatch):
    """不同文本连续调用（均缓存未命中）→ 第二次先 sleep 补足 0.5s。"""
    _patch_open(monkeypatch)
    fake_now = [100.0]
    monkeypatch.setattr(tc.time, "monotonic", lambda: fake_now[0])
    slept = []
    monkeypatch.setattr(tc.time, "sleep", lambda s: slept.append(s))
    tc.translate_text("first")
    tc.translate_text("second")
    assert slept, "第二次调用应触发 sleep"
    assert slept[0] >= 0.5


def test_throttle_no_sleep_when_interval_elapsed(monkeypatch):
    """间隔已超过 0.5s → 不 sleep。"""
    _patch_open(monkeypatch)
    fake_now = [100.0]
    monkeypatch.setattr(tc.time, "monotonic", lambda: fake_now[0])
    slept = []
    monkeypatch.setattr(tc.time, "sleep", lambda s: slept.append(s))
    tc.translate_text("first")
    fake_now[0] += 1.0  # 时间前进 1s
    tc.translate_text("second")
    assert slept == []