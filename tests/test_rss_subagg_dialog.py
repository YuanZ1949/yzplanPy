"""_AddAggregationDialog parent 模式测试。

离屏运行（QT_QPA_PLATFORM=offscreen），替身 store 记录调用。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock, patch, call

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication

# ── App 实例 ──────────────────────────────────────────────
app = QApplication.instance() or QApplication([])


# ── 替身 Store ────────────────────────────────────────────

class _StubStore:
    """最小化替身 store，记录 add_aggregation / update_aggregation 的调用参数。"""

    def __init__(self):
        self._aggs = {}          # id -> dict
        self._next_id = 1
        self._feeds = []
        self._tags = []
        self.add_calls = []
        self.update_calls = []
        self.refresh_calls = []
        self.titles_for = {}     # agg_id -> [title, ...]
        self.item_counts = {}    # agg_id -> int

    # ── 聚合 ──

    def get_aggregation(self, agg_id):
        return self._aggs.get(agg_id)

    def add_aggregation(self, name, agg_type="mixed", feed_ids=None, tags=None,
                        kw_required=None, kw_optional=None, kw_forbidden=None,
                        sort_order=0, parent_id=0, similarity_threshold=0.55):
        nid = self._next_id
        self._next_id += 1
        rec = {
            "id": nid, "name": name, "agg_type": agg_type,
            "feed_ids": str(feed_ids or []), "tags": str(tags or []),
            "kw_required": str(kw_required or []), "kw_optional": str(kw_optional or []),
            "kw_forbidden": str(kw_forbidden or []),
            "parent_id": parent_id, "similarity_threshold": similarity_threshold,
        }
        self._aggs[nid] = rec
        self.add_calls.append({
            "name": name, "agg_type": agg_type,
            "feed_ids": feed_ids, "tags": tags,
            "kw_required": kw_required, "kw_optional": kw_optional,
            "kw_forbidden": kw_forbidden,
            "parent_id": parent_id,
            "similarity_threshold": similarity_threshold,
        })
        return nid

    def update_aggregation(self, agg_id, **kwargs):
        self.update_calls.append({"agg_id": agg_id, **kwargs})

    def refresh_aggregation(self, agg_id):
        self.refresh_calls.append(agg_id)

    def aggregation_titles(self, agg_id):
        return self.titles_for.get(agg_id, [])

    def get_aggregation_item_count(self, agg_id):
        return self.item_counts.get(agg_id, 0)

    # ── 成员（非 parent 模式用）──

    def list_feeds(self):
        return self._feeds

    def list_tags(self):
        return self._tags


# ── Helpers ──────────────────────────────────────────────

def _make_parent(store, name="ParentMix", parent_id=1):
    """创建并注册一条父聚合记录。"""
    rec = {
        "id": parent_id, "name": name, "agg_type": "mixed",
        "feed_ids": "[1,2]", "tags": "[]",
        "kw_required": "[]", "kw_optional": "[]", "kw_forbidden": "[]",
        "parent_id": 0, "similarity_threshold": 0.55,
    }
    store._aggs[parent_id] = rec
    return rec


def _make_child(store, parent_id=1, agg_id=10, name="ChildKey",
                agg_type="keyword", similarity_threshold=0.55):
    """创建并注册一条子聚合记录。"""
    rec = {
        "id": agg_id, "name": name, "agg_type": agg_type,
        "feed_ids": "[]", "tags": "[]",
        "kw_required": "[]", "kw_optional": "[]", "kw_forbidden": "[]",
        "parent_id": parent_id, "similarity_threshold": similarity_threshold,
    }
    store._aggs[agg_id] = rec
    return rec


# ── Tests ────────────────────────────────────────────────

@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_parent_mode_new_type_combo_2_items(mock_bg):
    """parent 模式下类型下拉仅 keyword + similarity 两项。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    parent_rec = _make_parent(store)

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=parent_rec["id"])

    assert dlg.combo_type.count() == 2
    keys = [dlg.combo_type.itemData(i) for i in range(2)]
    assert keys == ["keyword", "similarity"]


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_parent_mode_no_member_list(mock_bg):
    """parent 模式下 member_list 为 None。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    assert dlg.member_list is None


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_parent_mode_auto_extract_button(mock_bg):
    """parent 模式下自动提取按钮存在，点击后 store.aggregation_titles 被调用并填充 in_required。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    parent_rec = _make_parent(store)
    store.titles_for[1] = ["AI Trend 2026", "AI in Healthcare", "Python Tips"]

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=parent_rec["id"])

    assert hasattr(dlg, "btn_auto_extract")
    # 模拟点击
    dlg._on_auto_extract()
    assert store.titles_for[1]  # sanity
    # in_required 应被填充（ai 和 healthcare 是高频词）
    text = dlg.in_required.text().strip()
    assert len(text) > 0, "自动提取后 in_required 应非空"
    assert "ai" in text.lower(), f"in_required 应包含 'ai': {text}"
    # optional / forbidden 被清空
    assert dlg.in_optional.text() == ""
    assert dlg.in_forbidden.text() == ""


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_parent_mode_spin_threshold_default_055(mock_bg):
    """similarity 类型下 spin_threshold 可见且默认 0.55。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    # 默认类型 keyword → spin 被隐藏
    assert dlg.spin_threshold.isHidden()

    # 切换到 similarity → spin 不再被隐藏（isVisible 要求父窗口 show，用 not isHidden 代替）
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    assert not dlg.spin_threshold.isHidden()
    assert dlg.spin_threshold.value() == pytest.approx(0.55)


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_parent_mode_save_add_keyword(mock_bg):
    """parent 模式 keyword 类型：add 调用含 parent_id，不含 similarity_threshold。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    parent_rec = _make_parent(store)
    store.item_counts[1] = 42

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=parent_rec["id"])
    dlg.in_name.setText("TestKeyword")
    # keyword 类型是默认的
    assert dlg.combo_type.currentData() == "keyword"
    dlg.in_required.setText("AI Python")

    # 点保存
    dlg._on_ok()

    assert len(store.add_calls) == 1
    c = store.add_calls[0]
    assert c["name"] == "TestKeyword"
    assert c["agg_type"] == "keyword"
    assert c["parent_id"] == 1
    # keyword 类型不传 similarity_threshold（保留默认 0.55）
    assert c["similarity_threshold"] == 0.55


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_parent_mode_save_add_similarity(mock_bg):
    """parent 模式 similarity 类型：add 调用含 parent_id 与自定义 threshold。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    parent_rec = _make_parent(store)

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=parent_rec["id"])
    dlg.in_name.setText("TestSimilarity")
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    dlg.spin_threshold.setValue(0.70)

    dlg._on_ok()

    assert len(store.add_calls) == 1
    c = store.add_calls[0]
    assert c["name"] == "TestSimilarity"
    assert c["agg_type"] == "similarity"
    assert c["parent_id"] == 1
    assert c["similarity_threshold"] == 0.70


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_parent_mode_window_title(mock_bg):
    """parent 模式窗口标题。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)
    assert dlg.windowTitle() == "新建二级条目"

    # 编辑模式
    child = _make_child(store, parent_id=1, agg_id=10)
    dlg2 = _AddAggregationDialog(owner, MagicMock(), agg_id=10)
    assert dlg2.windowTitle() == "编辑二级条目"


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_top_level_mode_requires_members(mock_bg):
    """顶层模式（非 parent）仍要求成员。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock())
    dlg.in_name.setText("TopLevelAgg")

    # 没有成员 → _on_ok 会发 warning（QMessageBox），但在 offscreen 下我们检查 call
    # store 应没有 add 调用
    with patch("modules.rss_aggregator.dialogs_f.QtWidgets.QMessageBox"):
        dlg._on_ok()
    assert len(store.add_calls) == 0, "无成员时不应调用 add_aggregation"


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_top_level_mode_4_type_items(mock_bg):
    """非 parent 模式下类型下拉有 4 项。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock())
    assert dlg.combo_type.count() == 4


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_top_level_mode_has_member_list(mock_bg):
    """非 parent 模式下 member_list 是 QListWidget。"""
    from PySide6.QtWidgets import QListWidget
    store = _StubStore()
    owner = MagicMock()
    owner.store = store

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock())
    assert isinstance(dlg.member_list, QListWidget)


@patch("modules.rss_aggregator.dialogs_f._bind_geometry")
def test_parent_mode_edit_existing_passes_parent_id_and_threshold(mock_bg):
    """编辑已有子聚合时，update 调用含 parent_id 与 similarity_threshold。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store, parent_id=5, name="BigParent")
    _make_child(store, parent_id=5, agg_id=20, name="OldChild",
                agg_type="similarity", similarity_threshold=0.80)

    from modules.rss_aggregator.dialogs_f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), agg_id=20)
    dlg.in_name.setText("RenamedChild")
    # similarity 类型应已选中
    dlg.spin_threshold.setValue(0.60)

    dlg._on_ok()

    assert len(store.update_calls) == 1
    u = store.update_calls[0]
    assert u["agg_id"] == 20
    assert u["parent_id"] == 5
    assert u["similarity_threshold"] == 0.60
    # 不应包含 feed_ids / tags（parent 模式不收集成员）
    assert "feed_ids" not in u
    assert "tags" not in u
