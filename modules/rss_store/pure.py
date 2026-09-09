"""modules/rss_store slice: pure helpers.

Spliced from modules/rss_store.py by T13 codebase-reorg.
"""
import base64
import hashlib
import re
from email.utils import parsedate_to_datetime


# ── 辅助函数 ──────────────────────────────────────────────────
def _hash(title, link):
    norm = "{}|{}".format((title or "").strip().lower(), (link or "").strip().lower())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


def _is_magnet_or_torrent(link):
    if not link:
        return False
    lower = link.strip().lower()
    if lower.startswith("magnet:"):
        return True
    if lower.endswith(".torrent"):
        return True
    return False


_MAGNET_BTIH_RE = re.compile(r"[?&]xt=urn:btih:([0-9a-fA-F]{40})")
# BTIH 支持两种编码：40 位十六进制 或 32 位 Base32(A-Z2-7，不含 0/1/8/9)
_MAGNET_BTIH_B32_RE = re.compile(r"[?&]xt=urn:btih:([A-Za-z2-7]{32})")
_HEX40_RE = re.compile(r"\b([0-9a-fA-F]{40})\b")


def b32_to_hex(b32):
    """32 位 Base32 BTIH -> 40 位小写十六进制。非法输入返回 None。"""
    if not b32:
        return None
    s = b32.strip().upper()
    if len(s) != 32 or not all(ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for ch in s):
        return None
    try:
        raw = base64.b32decode(s)
    except Exception:
        return None
    return raw.hex()


def normalize_btih(value):
    """将任意 BTIH 编码规范化为 40 位小写十六进制。无法识别返回原样。"""
    if not value:
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("ascii")
        except Exception:
            return value
    s = value.strip()
    if len(s) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in s):
        return s.lower()
    if len(s) == 32:
        hx = b32_to_hex(s)
        if hx:
            return hx
    return value


def extract_btih(link):
    """从链接/文本中提取磁力 info-hash 并规范化为 40 位小写十六进制。
    支持 40 位 hex 与 32 位 Base32 BTIH 两种编码。无则返回空。"""
    if not link:
        return ""
    if isinstance(link, str):
        m = _MAGNET_BTIH_RE.search(link)
        if m:
            return m.group(1).lower()
        m = _MAGNET_BTIH_B32_RE.search(link)
        if m:
            return normalize_btih(m.group(1)) or ""
        # 纯 hash 或磁力/种子名里内嵌的连续 40 位 hex
        m = _HEX40_RE.search(link)
        if m:
            return m.group(1).lower()
    return ""


def _normalize_published(published):
    if not published:
        return ""
    try:
        dt = parsedate_to_datetime(published)
        return dt.isoformat()
    except Exception:
        pass
    return published


def _estimate_read_time(description):
    if not description:
        return 1
    text = re.sub(r"<[^>]+>", "", description)
    words = len(text.split())
    return max(1, words // 200)


def _extract_image(description, link=""):
    if not description:
        return ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _detect_encoding(content):
    try:
        import chardet  # type: ignore[reportMissingImports]
        result = chardet.detect(content[:4096])
        return result.get("encoding") or "utf-8"
    except ImportError:
        return "utf-8"
