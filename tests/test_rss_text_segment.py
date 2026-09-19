"""text_segment：jieba 中文分词 + 词性过滤 + 停用词并集 + 回退。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from modules.rss_aggregator.text_segment import (
    DEFAULT_STOP_WORDS, available, segment_titles,
)


def test_segment_titles_basic_cjk():
    titles = ["海贼王第1000话高清下载", "海贼王第1001话在线观看"]
    result = segment_titles(titles, top_n=50)
    words = [w for w, _ in result]
    assert "海贼王" in words
    assert "第" not in words  # 助词/数词组合被词性过滤或停用词剔除


def test_segment_titles_filters_stopwords_union():
    titles = ["海贼王高清下载", "海贼王在线观看"]
    result = segment_titles(titles, top_n=50, extra_stop_words=["海贼王"])
    words = [w for w, _ in result]
    assert "海贼王" not in words  # 用户自定义停用词生效
    assert "高清" not in words    # 内置停用词生效


def test_segment_titles_top_n_cap():
    # 生成 400 个各含唯一 2 字 CJK 词的标题，确保 >200 个独立合格 token
    chars1 = [chr(0x4E00 + i) for i in range(20)]
    chars2 = [chr(0x5000 + i) for i in range(20)]
    titles = [f"{c1}{c2}新闻" for c1 in chars1 for c2 in chars2]
    result = segment_titles(titles, top_n=500)
    assert len(result) <= 200  # 硬上限


def test_segment_titles_empty():
    assert segment_titles([]) == []


def test_available_returns_bool():
    assert isinstance(available(), bool)


def test_default_stop_words_is_frozenset():
    assert isinstance(DEFAULT_STOP_WORDS, frozenset)
    assert "下载" in DEFAULT_STOP_WORDS


# ── Todo 18: segment_titles(granularity) n-gram 高频词 ─────────

# 固定标题集：golden 参考在改动前捕获（jieba 路径）
_GOLDEN_TITLES = [
    "三体 第一季 01",
    "三体 第一季 02",
    "三体 第二季 01",
    "海贼王第1000话高清下载",
    "海贼王第1001话在线观看",
    "AI Trend 2026",
    "Python Tips & Tricks",
    "Mixed 中文 English 123",
]

# 改动前 segment_titles(_GOLDEN_TITLES, top_n=50) 的逐字节输出（jieba 路径）
_GOLDEN_JIEBA = [
    ("三体", 3), ("第一季", 2), ("第二季", 1), ("海贼王", 2),
    ("ai", 1), ("trend", 1), ("python", 1), ("tips", 1),
    ("tricks", 1), ("mixed", 1), ("中文", 1), ("english", 1),
]

# 改动前 jieba 不可用（_jieba=None 且 _ensure_jieba 空转）时的正则回退输出
_GOLDEN_REGEX = [
    ("三体", 3), ("第一季", 2), ("第二季", 1),
    ("海贼王第1000话高清下载", 1), ("海贼王第1001话在线观看", 1),
    ("ai", 1), ("trend", 1), ("python", 1), ("tips", 1),
    ("tricks", 1), ("mixed", 1), ("中文", 1), ("english", 1),
]


def test_segment_titles_granularity1_identical_to_baseline():
    """granularity=1（默认）输出与改动前逐字节一致。"""
    assert segment_titles(_GOLDEN_TITLES, top_n=50) == _GOLDEN_JIEBA
    assert segment_titles(_GOLDEN_TITLES, top_n=50, granularity=1) == _GOLDEN_JIEBA


def test_segment_titles_granularity3_ngram_entries():
    """granularity=3 在「三体 第一季 蓝光」类标题上产出 3-gram 词条。"""
    titles = ["三体 第一季 蓝光", "三体 第一季 蓝光", "三体 第二季 蓝光"]
    g1 = dict(segment_titles(titles, top_n=50, granularity=1))
    g3 = dict(segment_titles(titles, top_n=50, granularity=3))
    assert "三体" in g1 and "第一季" in g1 and "蓝光" in g1
    assert g3["三体 第一季 蓝光"] == 2
    assert g3["三体 第二季 蓝光"] == 1


def test_segment_titles_granularity_clamped():
    """越界粒度（0/99）被钳制到 [1, 10]。"""
    titles = ["三体 第一季 蓝光", "三体 第一季 蓝光"]
    assert segment_titles(titles, top_n=50, granularity=0) == segment_titles(
        titles, top_n=50, granularity=1)
    assert segment_titles(titles, top_n=50, granularity=99) == segment_titles(
        titles, top_n=50, granularity=10)


def test_segment_titles_granularity1_regex_fallback_when_jieba_unavailable(monkeypatch):
    """jieba 不可用时 granularity=1 仍走正则回退且与旧实现一致。"""
    import modules.rss_aggregator.text_segment as ts
    monkeypatch.setattr(ts, "_jieba", None)
    monkeypatch.setattr(ts, "_ensure_jieba", lambda: None)
    assert segment_titles(_GOLDEN_TITLES, top_n=50) == _GOLDEN_REGEX
    assert segment_titles(_GOLDEN_TITLES, top_n=50, granularity=1) == _GOLDEN_REGEX


# ── Todo 2430: 块边界感知短语（粒度>1 不跨分隔符，支持完整短语）──

_BLOCK_TITLES = [
    "[Sub] Mushoku Tensei III: Isekai Ittara Honki Dasu [02][1080P][BIG5]",
    "[Sub] Mushoku Tensei III: Isekai Ittara Honki Dasu [03][1080P][BIG5]",
]


def test_segment_titles_granularity2_full_phrase_block():
    """粒度 2：冒号/方括号/数字后语义断点内的连续实词块以完整短语输出。

    副题块 [isekai, ittara, honki, dasu] 两标题同现 → 完整短语可计数；
    完整短语与滑动窗口共存（双词窗口仍输出），且同字符串不重复计数。
    """
    result = dict(segment_titles(_BLOCK_TITLES, top_n=100, granularity=2))
    assert result.get("isekai ittara honki dasu", 0) >= 1
    assert "mushoku tensei" in result
    # 「mushoku tensei iii」3 词块：完整块 ≠ 任一 2-gram 窗口，应作为一项输出
    assert "mushoku tensei iii" in result


def test_segment_titles_blocks_do_not_cross_separators():
    """块不跨分隔符：方括号/冒号/数字两侧的词不会跨边界组合。"""
    titles = ["[Group] Name: Second Season 01 [1080P]",
              "[Group] Name: Second Season 02 [1080P]"]
    result = dict(segment_titles(titles, top_n=100, granularity=2))
    # 「Second Season」是冒号/数字/方括号包围出的连续实词块 → 完整短语
    assert result.get("second season", 0) >= 1
    for gram in result:
        assert "[" not in gram and "]" not in gram, gram
        assert ":" not in gram, gram
        for part in gram.split():
            assert not part.isdigit(), f"数字词不应出现在组合里: {gram}"


def test_segment_titles_granularity2_full_phrase_no_double_count():
    """3 词块在粒度 3 时完整块==唯一窗口，不得重复计数。"""
    titles = ["三体 第一季 蓝光", "三体 第一季 蓝光"]
    g3 = dict(segment_titles(titles, top_n=50, granularity=3))
    assert g3["三体 第一季 蓝光"] == 2