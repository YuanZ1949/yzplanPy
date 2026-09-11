"""翻译核心：Google Translate 免费 API 调用 + OpenAI 兼容 LLM 大模型翻译。

`translate_text()` 是对外薄封装（provider: google | llm）；
`_fetch_google()` 是 Google 私有实现；`translate_with_llm()` 是 LLM 实现。
"""
import json
import time
import urllib.parse
import urllib.request

_GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
_HTTP_TIMEOUT = 5
_LLM_TIMEOUT = 10
_MIN_INTERVAL = 0.5
_CACHE_MAX = 200

_LLM_CONFIG_KEY = "modules.translator.llm"
_LLM_FALLBACK_PREFIX = "[已回退到Google翻译] "

# 有序 (显示名, 语言代码) 列表，供 UI 下拉框复用
LANGUAGES = [
    ("自动检测", "auto"),
    ("中文", "zh"),
    ("英语", "en"),
    ("日语", "ja"),
    ("韩语", "ko"),
    ("法语", "fr"),
    ("德语", "de"),
    ("西班牙语", "es"),
]

_SUPPORTED = {"zh", "en", "ja", "ko", "fr", "de", "es"}
_DST_MAP = {"zh": "zh-CN"}

# 测试接缝：monkeypatch 此函数即可离线模拟网络响应
_http_open = urllib.request.urlopen

_cache = {}
_last_call = 0.0


def _normalize(code, default):
    """语言代码规范化：未知代码回退到 default；zh 映射为 zh-CN。"""
    if not code:
        return default
    code = code.strip()
    if code not in _SUPPORTED:
        return default
    return _DST_MAP.get(code, code)


def _fetch_google(text, src, dst):
    """调用 Google Translate 免费端点，返回翻译文本（私有实现）。"""
    params = urllib.parse.urlencode({
        "client": "gtx",
        "sl": src,
        "tl": dst,
        "dt": "t",
        "q": text,
    })
    url = f"{_GOOGLE_URL}?{params}"
    with _http_open(url, timeout=_HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    chunks = data[0]
    if not chunks:
        return ""
    # 兼容两种格式：真实端点 [[chunk, ...], ...] 与单块 [translated, src, ...]
    if isinstance(chunks[0], list):
        return "".join(c[0] for c in chunks if c and c[0])
    return chunks[0] or ""


def _llm_config() -> dict:
    """读取 LLM 配置（modules.translator.llm.{api_url,api_key,model}）。"""
    from core.config import AppConfig
    cfg = AppConfig()
    return {
        "api_url": cfg.get(f"{_LLM_CONFIG_KEY}.api_url", ""),
        "api_key": cfg.get(f"{_LLM_CONFIG_KEY}.api_key", ""),
        "model": cfg.get(f"{_LLM_CONFIG_KEY}.model", ""),
    }


def llm_configured():
    """LLM 配置是否完整（api_url / api_key / model 均非空）。"""
    cfg = _llm_config()
    return bool(cfg["api_url"] and cfg["api_key"] and cfg["model"])


def get_provider():
    """读取当前翻译 provider（modules.translator.llm.provider）。"""
    from core.config import AppConfig
    return AppConfig().get(f"{_LLM_CONFIG_KEY}.provider", "google") or "google"


def set_provider(value):
    """持久化翻译 provider 到配置。"""
    from core.config import AppConfig
    AppConfig().set(f"{_LLM_CONFIG_KEY}.provider", value)


def translate_with_llm(text, src_lang="auto", dst_lang="zh-CN"):
    """调用 OpenAI 兼容 LLM 接口翻译文本。

    配置缺失或任何失败（网络 / JSON 解析 / 空结果）均返回 None，由调用方回退。
    api_key 仅作为 Authorization 头发送，绝不写入日志。
    """
    if not text:
        return None
    cfg = _llm_config()
    api_url = (cfg.get("api_url") or "").strip()
    api_key = cfg.get("api_key") or ""
    model = cfg.get("model") or ""
    if not api_url or not api_key or not model:
        return None
    src = _normalize(src_lang, "auto")
    dst = _normalize(dst_lang, "zh-CN")
    url = api_url.rstrip("/") + "/chat/completions"
    system_prompt = (
        "You are a professional translator. Translate the following text "
        f"from {src} to {dst}. Only output the translation, no explanations."
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        "temperature": 0.3,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with _http_open(req, timeout=_LLM_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        result = content.strip()
        return result or None
    except Exception:
        return None


def translate_text(text, src_lang="auto", dst_lang="zh-CN", provider="google"):
    """翻译文本。provider: "google" | "llm"；LLM 失败自动回退 Google。

    失败时返回 '[翻译失败: ...]'，绝不抛出异常。
    """
    global _last_call
    if not text:
        return ""
    src = _normalize(src_lang, "auto")
    dst = _normalize(dst_lang, "zh-CN")
    key = (text, src, dst, provider)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    if provider == "llm":
        result = translate_with_llm(text, src_lang=src, dst_lang=dst)
        if result is not None:
            _cache[key] = result
            if len(_cache) > _CACHE_MAX:
                _cache.pop(next(iter(_cache)))
            return result
        # LLM 失败/未配置 → 回退 Google，并加前缀注释（同样受速率限制约束）
        now = time.monotonic()
        delta = _last_call + _MIN_INTERVAL - now
        if delta > 0:
            time.sleep(delta)
        try:
            google_result = _fetch_google(text, src, dst)
        except Exception:
            _last_call = time.monotonic()
            return "[翻译失败: LLM 与 Google 均不可用]"
        _last_call = time.monotonic()
        prefixed = _LLM_FALLBACK_PREFIX + google_result
        _cache[key] = prefixed
        if len(_cache) > _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        return prefixed
    # 速率限制：距上次真实网络调用不足 0.5s 则先等待（缓存命中不受限）
    now = time.monotonic()
    delta = _last_call + _MIN_INTERVAL - now
    if delta > 0:
        time.sleep(delta)
    try:
        result = _fetch_google(text, src, dst)
    except Exception as exc:
        _last_call = time.monotonic()
        return f"[翻译失败: {exc}]"
    _last_call = time.monotonic()
    _cache[key] = result
    if len(_cache) > _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    return result