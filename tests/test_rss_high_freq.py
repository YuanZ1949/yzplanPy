"""RSS 高频词标签测试：纯函数 analyze_high_freq_titles + 对话框冒烟。

纯函数用例验证标题高频词提取；子进程冒烟验证 _AddAggregationDialog
similarity 模式下按钮/chips/关键词填充正确渲染与交互。
"""
import os
import sys

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


def test_analyze_high_freq_cjk_whole_run_token():
    """中文标题按 _WORD_RE 整段切词：整条标题作为单个 token（_extract_keywords 既有行为）。"""
    from modules.rss_aggregator.text_utils import analyze_high_freq_titles
    result = analyze_high_freq_titles(["今天天气很好", "今天适合跑步", "天气真的不错"])
    assert result == ["今天天气很好", "今天适合跑步", "天气真的不错"]


def test_analyze_high_freq_is_wrapper():
    """确认 analyze_high_freq_titles 复用 _extract_keywords。"""
    from modules.rss_aggregator.text_utils import analyze_high_freq_titles, _extract_keywords
    titles = ["测试数据一", "测试数据二", "测试数据三"]
    assert analyze_high_freq_titles(titles, top_n=5) == _extract_keywords(titles, top_n=5)


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

    # fake store
    class FakeStore:
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
        def aggregation_titles(self, agg_id):
            return []

    owner = type("O", (), {"store": FakeStore()})()
    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, None)

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

    # hf_flow 内应有 chip 按钮，且含提取出的标题 token（_WORD_RE 整段切词）
    chip_texts = []
    flow_layout = dlg.hf_flow.layout()
    for i in range(flow_layout.count()):
        item = flow_layout.itemAt(i)
        w = item.widget() if item else None
        if w is not None and hasattr(w, "text"):
            chip_texts.append(w.text())
    assert len(chip_texts) > 0, "应有 chip 按钮渲染"
    assert "今天天气很好" in chip_texts, f"chip 应含标题 token，实际: {chip_texts}"

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
