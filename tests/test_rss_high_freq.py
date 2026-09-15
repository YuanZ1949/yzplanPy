"""RSS 高频词标签测试：纯函数 analyze_high_freq_titles + 对话框冒烟。

纯函数用例验证标题高频词提取；子进程冒烟验证 _AddAggregationDialog
similarity 模式下按钮/chips/关键词填充正确渲染与交互。
"""
import os
import sys
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ── 纯函数用例 ────────────────────────────────────────────────

def test_analyze_high_freq_basic():
    """基础：高频词按频降序排前，停用词被过滤。"""
    from modules.rss_aggregator.text_utils import analyze_high_freq_titles
    result = analyze_high_freq_titles([
        "python the great",
        "python rocks",
        "great day",
    ])
    assert result[0] == "python"  # 频次=2 排前
    assert result[1] == "great"   # 频次=2 排前
    assert "the" not in result    # 停用词被过滤


def test_analyze_high_freq_filters_stopwords():
    """停用词与单字、纯数字应被过滤。"""
    from modules.rss_aggregator.text_utils import analyze_high_freq_titles
    result = analyze_high_freq_titles(["the a an of", "x y z", "123 456"])
    assert result == []


def test_analyze_high_freq_empty():
    """空列表返回空列表。"""
    from modules.rss_aggregator.text_utils import analyze_high_freq_titles
    assert analyze_high_freq_titles([]) == []


def test_analyze_high_freq_top_n():
    """top_n 限制返回数量。"""
    from modules.rss_aggregator.text_utils import analyze_high_freq_titles
    result = analyze_high_freq_titles([
        "apple pie",
        "apple tart",
        "apple crisp",
    ], top_n=2)
    assert len(result) == 2
    assert result[0] == "apple"


def test_analyze_high_freq_is_wrapper():
    """确认 analyze_high_freq_titles 复用 _extract_keywords。"""
    from modules.rss_aggregator.text_utils import analyze_high_freq_titles, _extract_keywords
    titles = ["测试数据一", "测试数据二", "测试数据三"]
    assert analyze_high_freq_titles(titles, top_n=5) == _extract_keywords(titles, top_n=5)


def test_chips_pool_is_results_minus_buckets():
    """chips 池 ≡ 分析结果全集 − 三桶已解析词。"""
    from modules.rss_aggregator.dialogs.builders import _chips_pool
    results = [("海贼王", 5), ("火影", 3), ("下载", 2)]
    buckets = {"required": ["海贼王"], "optional": [], "forbidden": ["下载"]}
    pool = _chips_pool(results, buckets)
    assert pool == [("火影", 3)]


def test_chips_text_shows_frequency():
    from modules.rss_aggregator.dialogs.builders import _chip_text
    assert _chip_text("海贼王", 5) == "海贼王 · 5"


# ── 子进程冒烟：_AddAggregationDialog chips 渲染与交互 ───────

def test_high_freq_dialog_smoke_subprocess():
    """Subprocess isolation: dialog chips render + chip click fills in_required + shift fills in_forbidden."""
    import subprocess
    from pathlib import Path
    child_name = "test_high_freq_dialog_smoke_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_rss_high_freq.py::{child_name}",
         "-q", "-s"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )
    assert "RSS_HIGH_FREQ_OK" in result.stdout.decode(errors="replace")


def test_high_freq_dialog_smoke_child():
    """Child: fake store → dialog → similarity type → analyze high freq → chip click → append keyword."""
    import tempfile
    from pathlib import Path

    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    # monkeypatch _bind_geometry 为 no-op（无窗口环境不安全）
    from modules.rss_aggregator import utils as _rss_utils
    _rss_utils._bind_geometry = lambda *a, **k: None

    # fake store — agg_id-sensitive: None/0 → [], else titles
    _TEST_AGG_ID = 42  # sentinel: valid non-parent agg_id for smoke test

    class FakeStore:
        def __init__(self):
            self.last_agg_id = None
        def list_tags(self):
            return ["科技"]
        def list_feeds(self):
            return []
        def get_aggregation(self, agg_id):
            return None
        def get_aggregation_item_count(self, agg_id):
            return 0
        def recent(self, limit=None, tags=None, **kw):
            return [
                {"title": "今天天气很好"},
                {"title": "今天适合跑步"},
                {"title": "天气真的不错"},
            ]
        def aggregation_titles(self, agg_id, limit=None):
            self.last_agg_id = agg_id
            if agg_id in (0, None):
                return []
            return ["今天天气很好", "今天适合跑步", "天气真的不错"]

    owner = type("O", (), {"store": FakeStore()})()
    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, None)
    # Assign valid agg_id so agg_id-sensitive FakeStore returns titles
    dlg.agg_id = _TEST_AGG_ID

    # 选择相似性类型
    type_idx = dlg.combo_type.findData("similarity")
    assert type_idx >= 0, "combo_type 应包含 similarity"
    dlg.combo_type.setCurrentIndex(type_idx)
    dlg._on_type_changed()

    dlg.show()
    for _ in range(5):
        app.processEvents()

    # _hf_group 应可见
    assert dlg._hf_group.isVisible(), "相似性模式下 _hf_group 应可见"

    # 选中标签列表第 0 项
    assert dlg.tag_list.count() > 0, "tag_list 应含标签"
    dlg.tag_list.item(0).setSelected(True)

    # 点击分析高频词按钮
    dlg.btn_high_freq.click()
    for _ in range(5):
        app.processEvents()

    # hf_flow 内应有 chip 按钮，且含 jieba 切出的名词（_ALLOWED_FLAGS 含 n）
    chip_texts = []
    flow_layout = dlg._hf_chips_layout
    for i in range(flow_layout.count()):
        item = flow_layout.itemAt(i)
        w = item.widget() if item else None
        if w is not None and hasattr(w, "text"):
            chip_texts.append(w.text())
    assert len(chip_texts) > 0, "应有 chip 按钮渲染"
    assert any("天气" in t for t in chip_texts), f"chip 应含 jieba 名词，实际: {chip_texts}"

    # chip 点击应填入 in_required
    dlg._on_chip_clicked("今天")
    assert "今天" in dlg.in_required.text(), f"in_required 应含 '今天'，实际: '{dlg.in_required.text()}'"

    # _append_keyword(to_forbidden=True) 应填入 in_forbidden
    dlg._append_keyword("天气", to_forbidden=True)
    assert "天气" in dlg.in_forbidden.text(), f"in_forbidden 应含 '天气'，实际: '{dlg.in_forbidden.text()}'"

    # 重复添加同一词不崩
    dlg._on_chip_clicked("今天")
    dlg._append_keyword("天气", to_forbidden=True)

    # 无 titles 场景不崩
    class EmptyStore(FakeStore):
        def recent(self, limit=None, tags=None, **kw):
            return []
    dlg.store = EmptyStore()
    dlg.btn_high_freq.click()
    for _ in range(5):
        app.processEvents()

    dlg.close()
    for _ in range(5):
        app.processEvents()
    print("RSS_HIGH_FREQ_OK")


# ── 高频词分析 parent 回退测试 ─────────────────────────────

class _AggIdStore:
    """FakeStore agg_id-sensitive: returns [] for None/0, titles otherwise."""

    def __init__(self):
        self.last_agg_id = None
        self._titles = [
            "海贼王漫画", "海贼王动画", "火影忍者漫画",
            "火影忍者动画", "死神漫画",
        ]

    def aggregation_titles(self, agg_id, limit=None):
        self.last_agg_id = agg_id
        if agg_id in (0, None):
            return []
        return list(self._titles)


def _ensure_qapp():
    """Ensure QApplication exists for widget tests."""
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return QtCore, QtGui, QtWidgets, app


class _DialogStub:
    """Minimal dialog stub; build_high_freq_group fills the _hf_* attributes."""

    def __init__(self, store, agg_id=None, parent_agg=None):
        QtCore, QtGui, QtWidgets, app = _ensure_qapp()
        self.owner = type("O", (), {"store": store})()
        self.agg_id = agg_id
        self._parent_agg = parent_agg
        self.in_required = QtWidgets.QLineEdit()
        self.in_optional = QtWidgets.QLineEdit()
        self.in_forbidden = QtWidgets.QLineEdit()
        # populated by build_high_freq_group
        self._hf_results: Any = []
        self._hf_chips_layout: Any = None
        self._hf_selected: Any = set()


def _make_dialog_stub(store, agg_id=None, parent_agg=None):
    """Minimal dialog stub wired through build_high_freq_group."""
    _, _, QtWidgets, _ = _ensure_qapp()
    from modules.rss_aggregator.dialogs.builders import build_high_freq_group

    parent = QtWidgets.QWidget()
    stub = _DialogStub(store, agg_id=agg_id, parent_agg=parent_agg)
    build_high_freq_group(stub, parent)
    return stub, parent


def _click_analyze(stub):
    """Trigger the 分析高频词 button and process events."""
    _, _, _, app = _ensure_qapp()
    stub.btn_high_freq.click()
    for _ in range(3):
        app.processEvents()


def test_analyze_high_freq_uses_parent_agg_id():
    """Parent mode: dialog.agg_id=None + _parent_agg={id:7} → store receives 7."""
    store = _AggIdStore()
    stub, parent = _make_dialog_stub(store, agg_id=None, parent_agg={"id": 7})

    _click_analyze(stub)

    assert store.last_agg_id == 7, (
        f"store should receive parent agg_id 7, got {store.last_agg_id}"
    )
    assert len(stub._hf_results) > 0, (
        "results should be non-empty when parent titles are used"
    )
    assert stub._hf_chips_layout.count() > 0, (
        "chips should be rendered with parent titles"
    )
    parent.close()


def test_analyze_high_freq_edit_uses_own_agg_id():
    """Editing existing sub-agg: dialog.agg_id=8 → store receives 8, not parent id."""
    store = _AggIdStore()
    stub, parent = _make_dialog_stub(store, agg_id=8, parent_agg={"id": 7})

    _click_analyze(stub)

    assert store.last_agg_id == 8, (
        f"editing existing agg should use own agg_id 8, got {store.last_agg_id}"
    )
    parent.close()


def test_analyze_high_freq_no_parent_no_agg_id():
    """_parent_agg=None + agg_id=None → no exception, results empty."""
    store = _AggIdStore()
    stub, parent = _make_dialog_stub(store, agg_id=None, parent_agg=None)

    # Should not raise
    _click_analyze(stub)

    assert store.last_agg_id is None
    assert stub._hf_results == [], "no titles without parent or own agg_id"
    parent.close()


def test_count_aggregation_hits(tmp_path):
    """S1：count_aggregation_hits 按与 refresh_aggregation 相同的条件统计命中。"""
    from modules.rss_store.store import RssStore
    store = RssStore(str(tmp_path / "t.db"))
    store.add_feed("TestFeed", "http://test/rss", "test")
    feed_id = store.list_feeds()[0]["id"]
    entries = [
        {"title": f"海贼王{i}话", "link": f"http://x/{i}", "description": ""}
        for i in range(5)
    ]
    store.ingest("test", entries, feed_id=feed_id)
    agg = {"agg_type": "keyword", "kw_required": ["海贼王"],
           "feed_ids": [feed_id], "tags": []}
    assert store.count_aggregation_hits(agg) == 5
