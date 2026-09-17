"""中文分词高频词提取：jieba 懒加载 + 词性过滤 + 停用词并集 + 正则回退。"""

import threading
from collections import Counter

from .text_utils import _STOP_WORDS, _WORD_RE, _ngram_join

_jieba = None
_jieba_lock = threading.Lock()

# 允许保留的词性：名词/专名/英文/数词/非语素字（字母数字串）
_ALLOWED_FLAGS = {"n", "nr", "ns", "nt", "nz", "eng", "m", "x"}

# 内置停用词：现有 19 个基础 + 内容站常见噪声词
DEFAULT_STOP_WORDS = frozenset(
    set(_STOP_WORDS) | {
        "下载", "在线", "高清", "全集", "最新", "更新", "资源",
        "免费", "字幕组", "观看", "视频", "地址", "链接", "分享",
    }
)

_TOP_N_HARD_CAP = 200


def available():
    """jieba 是否可用（首次调用触发懒加载）。"""
    _ensure_jieba()
    return _jieba is not None


def _ensure_jieba():
    global _jieba
    if _jieba is not None:
        return
    with _jieba_lock:
        if _jieba is not None:
            return
        try:
            import jieba.posseg as _posseg
            _jieba = _posseg
        except Exception:
            _jieba = None


def segment_titles(titles, top_n=50, extra_stop_words=None, granularity=1):
    """把标题列表汇成高频词表：频次降序，同频保持首现顺序。

    top_n 硬上限 200；jieba 不可用时回退 text_utils._WORD_RE 正则分词。
    granularity=1 时与旧行为逐字节一致（按过滤后单 token 计数）；
    granularity=n（2~10）时先对每条标题的过滤后 token 序列做 n-gram 合并再计数。
    越界粒度（<1 或 >10）被钳制到 [1, 10]。
    """
    if not titles:
        return []
    top_n = max(1, min(int(top_n), _TOP_N_HARD_CAP))
    stop = DEFAULT_STOP_WORDS | frozenset(extra_stop_words or [])
    from modules.rss_store.store_conn import MAX_SIMILARITY_GRANULARITY
    try:
        n = int(granularity)
    except (TypeError, ValueError):
        n = 1
    n = max(1, min(n, MAX_SIMILARITY_GRANULARITY))
    _ensure_jieba()
    counter = Counter()
    if _jieba is not None:
        for title in titles:
            toks = []
            for word, flag in _jieba.cut(title):
                if flag not in _ALLOWED_FLAGS:
                    continue
                w = word.strip().lower()
                if not w:
                    continue
                if len(w) < 2:
                    continue
                if w.isdigit():
                    continue
                if w in stop:
                    continue
                toks.append(w)
            for gram in _ngram_join(toks, n):
                counter[gram] += 1
    else:
        for title in titles:
            toks = [w for w in _WORD_RE.findall(title.lower())
                    if len(w) >= 2 and not w.isdigit() and w not in stop]
            for gram in _ngram_join(toks, n):
                counter[gram] += 1
    return list(counter.items())[:top_n]