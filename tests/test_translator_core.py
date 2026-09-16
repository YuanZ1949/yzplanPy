"""translator_core 测试：解析、缓存、失败、速率限制、LLM provider（全部离线，不触网）。"""
import json
import logging

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


# ── LLM provider ─────────────────────────────────────────────────

def _patch_llm_config(monkeypatch, **overrides):
    cfg = {
        "api_url": "https://llm.example.com/v1",
        "api_key": "sk-test",
        "model": "gpt-4o-mini",
    }
    cfg.update(overrides)
    monkeypatch.setattr(tc, "_llm_config", lambda: dict(cfg))
    return cfg


class _LLMResp:
    """模拟 LLM 端点响应（context manager）。"""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def _llm_canned(text="你好"):
    return json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")


def test_translate_with_llm_unconfigured_returns_none(monkeypatch):
    _patch_llm_config(monkeypatch, api_url="")
    assert tc.translate_with_llm("Hello") is None


def test_translate_with_llm_configured_correct_request(monkeypatch):
    _patch_llm_config(monkeypatch)
    captured = {}

    def _fake_open(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _LLMResp(_llm_canned())

    monkeypatch.setattr(tc, "_http_open", _fake_open)
    result = tc.translate_with_llm("Hello", dst_lang="zh-CN")
    assert result == "你好"
    req = captured["req"]
    assert req.full_url.endswith("/chat/completions")
    assert req.get_method() == "POST"
    assert captured["timeout"] == 10
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "gpt-4o-mini"
    assert body["temperature"] == 0.3
    assert body["messages"][0]["role"] == "system"
    assert "from auto to zh-CN" in body["messages"][0]["content"]
    assert body["messages"][1] == {"role": "user", "content": "Hello"}
    assert req.get_header("Authorization") == "Bearer sk-test"


def test_translate_text_llm_fallback_to_google(monkeypatch):
    _patch_llm_config(monkeypatch)
    monkeypatch.setattr(tc, "translate_with_llm", lambda *a, **k: None)
    monkeypatch.setattr(tc, "_fetch_google", lambda *a, **k: "你好")
    result = tc.translate_text("Hello", provider="llm")
    assert result.startswith("[已回退到Google翻译] 你好")


def test_translate_text_llm_success(monkeypatch):
    _patch_llm_config(monkeypatch)
    monkeypatch.setattr(tc, "translate_with_llm", lambda *a, **k: "translated")
    result = tc.translate_text("Hello", provider="llm")
    assert result == "translated"
    assert not result.startswith("[已回退到Google翻译]")


def test_api_key_not_logged(monkeypatch, caplog):
    _patch_llm_config(monkeypatch, api_key="sk-super-secret")
    monkeypatch.setattr(tc, "_http_open", lambda req, timeout=None: _LLMResp(_llm_canned()))
    with caplog.at_level(logging.DEBUG):
        tc.translate_with_llm("Hello")
    assert "sk-super-secret" not in caplog.text


def test_llm_fallback_respects_throttle(monkeypatch):
    """LLM 回退 Google 前同样受 0.5s 速率限制约束。"""
    _patch_llm_config(monkeypatch)
    monkeypatch.setattr(tc, "translate_with_llm", lambda *a, **k: None)
    monkeypatch.setattr(tc, "_fetch_google", lambda *a, **k: "你好")
    fake_now = [100.0]
    monkeypatch.setattr(tc.time, "monotonic", lambda: fake_now[0])
    slept = []
    monkeypatch.setattr(tc.time, "sleep", lambda s: slept.append(s))
    tc.translate_text("first", provider="llm")
    tc.translate_text("second", provider="llm")
    assert slept, "LLM 回退 Google 应触发 sleep"
    assert slept[0] >= 0.5