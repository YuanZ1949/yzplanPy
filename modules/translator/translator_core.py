"""翻译核心：Google Translate 免费 API 调用（无 key、不修改系统代理）。

`translate_text()` 是对外薄封装；`_fetch_google()` 是 Google 私有实现。
后续任务 22 可在此文件新增第二个 provider（如 LLM），保持 translate_text 签名不变。
"""
import json
import time
import urllib.parse
import urllib.request

_GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
_HTTP_TIMEOUT = 5
_MIN_INTERVAL = 0.5
_CACHE_MAX = 200

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


def translate_text(text, src_lang="auto", dst_lang="zh-CN"):
    """翻译文本。失败时返回 '[翻译失败: ...]'，绝不抛出异常。"""
    global _last_call
    if not text:
        return ""
    src = _normalize(src_lang, "auto")
    dst = _normalize(dst_lang, "zh-CN")
    key = (text, src, dst)
    cached = _cache.get(key)
    if cached is not None:
        return cached
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