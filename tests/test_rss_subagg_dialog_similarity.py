"""_AddAggregationDialog 相似性类型标签多选测试（Task 8）。

离屏运行，替身 store 记录调用。验证：
- 非 parent 模式创建 tag_list（QListWidget MultiSelection，含全部标签）
- 相似性类型切换时 tag_group / members_group / btn_auto_extract 可见性
- 相似性保存时从 tag_list 收集 tags
- 编辑已有相似性聚合时预选标签
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication, QListWidget, QAbstractItemView

app = QApplication.instance() or QApplication([])

from modules.rss_aggregator.dialogs.f import _AddAggregationDialog


class _StubStore:
    """最小化替身 store，记录 add_aggregation / update_aggregation 的调用参数。"""

    def __init__(self):
        self._aggs = {}
        self._next_id = 1
        self._feeds = []
        self._tags = []
        self.add_calls = []
        self.update_calls = []
        self.refresh_calls = []
        self.item_counts = {}

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

    def get_aggregation_item_count(self, agg_id):
        return self.item_counts.get(agg_id, 0)

    def list_feeds(self):
        return self._feeds

    def list_tags(self):
        return self._tags


def _make_owner(store):
    owner = MagicMock()
    owner.store = store
    return owner


def _make_sim_agg(store, agg_id=30, name="SimAgg", tags=("AI", "Python")):
    import json
    rec = {
        "id": agg_id, "name": name, "agg_type": "similarity",
        "feed_ids": "[]", "tags": json.dumps(list(tags)),
        "kw_required": "[]", "kw_optional": "[]", "kw_forbidden": "[]",
        "parent_id": 0, "similarity_threshold": 0.55,
    }
    store._aggs[agg_id] = rec
    return rec


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_top_level_similarity_has_tag_list(mock_bg):
    """非 parent 模式创建 tag_list：QListWidget、MultiSelection、含全部标签。"""
    store = _StubStore()
    store._tags = ["AI", "Python", "Rust"]
    dlg = _AddAggregationDialog(_make_owner(store), MagicMock())

    assert isinstance(dlg.tag_list, QListWidget)
    assert dlg.tag_list.selectionMode() == QAbstractItemView.MultiSelection
    texts = [dlg.tag_list.item(i).text() for i in range(dlg.tag_list.count())]
    assert texts == ["AI", "Python", "Rust"]


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_top_level_similarity_visibility_switch(mock_bg):
    """切换到相似性类型：tag_group 显示、members_group 隐藏、btn_auto_extract 显示。"""
    store = _StubStore()
    store._tags = ["AI"]
    dlg = _AddAggregationDialog(_make_owner(store), MagicMock())

    # 默认 mixed：tag_group 隐藏、members_group 显示、按钮隐藏
    assert dlg._tag_group.isHidden()
    assert not dlg._members_group.isHidden()
    assert dlg.btn_auto_extract.isHidden()

    # 切到 similarity
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    assert not dlg._tag_group.isHidden()
    assert dlg._members_group.isHidden()
    assert not dlg.btn_auto_extract.isHidden()

    # 切回 mixed
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("mixed"))
    assert dlg._tag_group.isHidden()
    assert not dlg._members_group.isHidden()
    assert dlg.btn_auto_extract.isHidden()


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_top_level_similarity_save_collects_tags(mock_bg):
    """相似性保存：从 tag_list 选中项收集 tags，add 调用含 tags。"""
    store = _StubStore()
    store._tags = ["AI", "Python", "Rust"]
    dlg = _AddAggregationDialog(_make_owner(store), MagicMock())
    dlg.in_name.setText("SimByTag")
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    # 选中 AI + Python
    for i in range(dlg.tag_list.count()):
        if dlg.tag_list.item(i).text() in ("AI", "Python"):
            dlg.tag_list.item(i).setSelected(True)

    dlg._on_ok()

    assert len(store.add_calls) == 1
    c = store.add_calls[0]
    assert c["name"] == "SimByTag"
    assert c["agg_type"] == "similarity"
    assert sorted(c["tags"]) == ["AI", "Python"]
    assert c["feed_ids"] == []


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_top_level_similarity_save_requires_tag(mock_bg):
    """相似性保存未选标签：warning 且不调用 add。"""
    store = _StubStore()
    store._tags = ["AI"]
    dlg = _AddAggregationDialog(_make_owner(store), MagicMock())
    dlg.in_name.setText("SimNoTag")
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))

    with patch("modules.rss_aggregator.dialogs.f.QtWidgets.QMessageBox"):
        dlg._on_ok()
    assert len(store.add_calls) == 0, "未选标签时不应调用 add_aggregation"


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_edit_similarity_preselects_tags(mock_bg):
    """编辑已有相似性聚合：tag_list 预选已保存标签。"""
    store = _StubStore()
    store._tags = ["AI", "Python", "Rust"]
    _make_sim_agg(store, tags=("AI", "Rust"))

    dlg = _AddAggregationDialog(_make_owner(store), MagicMock(), agg_id=30)

    selected = {item.text() for item in dlg.tag_list.selectedItems()}
    assert selected == {"AI", "Rust"}


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_edit_similarity_save_updates_tags(mock_bg):
    """编辑相似性聚合：update 调用含 tags（来自 tag_list 选中项）。"""
    store = _StubStore()
    store._tags = ["AI", "Python", "Rust"]
    _make_sim_agg(store, tags=("AI", "Rust"))

    dlg = _AddAggregationDialog(_make_owner(store), MagicMock(), agg_id=30)
    dlg.in_name.setText("SimEdited")
    # 改为只选 Python
    for i in range(dlg.tag_list.count()):
        dlg.tag_list.item(i).setSelected(dlg.tag_list.item(i).text() == "Python")

    dlg._on_ok()

    assert len(store.update_calls) == 1
    u = store.update_calls[0]
    assert u["agg_id"] == 30
    assert u["tags"] == ["Python"]
    assert u["feed_ids"] == []