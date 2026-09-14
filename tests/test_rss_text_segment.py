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