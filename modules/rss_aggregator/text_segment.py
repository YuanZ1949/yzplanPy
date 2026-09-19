"""中文分词高频词提取：jieba 懒加载 + 词性过滤 + 停用词并集 + 正则回退。"""

import re
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
    """把标题列表汇成高频词/短语表：频次降序，同频保持首现顺序。

    top_n 硬上限 200；jieba 不可用时回退 text_utils._WORD_RE 正则分词。
    granularity=1 时与旧行为逐字节一致（按过滤后单 token 计数）；
    granularity=n（2~10）时对每条标题的**连续实词块**做 n-gram 合并再计数，
    且每块额外输出完整块短语（与窗口去重，同字符串不重复计数）。

    被过滤的 token（非允许词性/纯数字/超短词/停用词）触发断块，组合不跨
    语义边界（分隔符/数字/括号两侧的词不会拼到一起），因而能适配出
    「Mushoku Tensei」这类带空格的完整短语，内部顺序保持原文不变。
    纯空白 token 不断块（英文短语「Python Tips」不因空格被拆）。
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

    def count_block(block):
        """整块计数：n==1 逐 token；n>=2 窗口 n-gram + 完整块短语（去重）。"""
        if n == 1:
            for w in block:
                counter[w] += 1
            return
        grams = _ngram_join(block, n)
        for gram in grams:
            counter[gram] += 1
        if len(block) >= n:
            full = " ".join(block)
            if full not in grams:
                counter[full] += 1

    if _jieba is not None:
        for title in titles:
            block = []
            for word, flag in _jieba.cut(title):
                w = word.strip().lower()
                if not w:
                    continue  # 纯空白：不断块（英文短语内的空格不拆）
                if (flag not in _ALLOWED_FLAGS or len(w) < 2
                        or w.isdigit() or w in stop):
                    count_block(block)
                    block = []  # 语义断点：开启新块
                    continue
                block.append(w)
            count_block(block)
    else:
        for title in titles:
            block = []
            prev_end = None
            for m in _WORD_RE.finditer(title.lower()):
                w = m.group(0)
                # 上词尾与本词头之间夹着非空白字符（标点/括号/横线等）= 断点
                if prev_end is not None and re.search(
                        r"[^\s]", title[prev_end:m.start()]):
                    count_block(block)
                    block = []
                prev_end = m.end()
                if len(w) < 2 or w.isdigit() or w in stop:
                    count_block(block)
                    block = []
                    continue
                block.append(w)
            count_block(block)
    return list(counter.items())[:top_n]