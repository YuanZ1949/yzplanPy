"""RSS 侧栏排序/筛选/选中恢复逻辑补测（_RssSidebar 扩充类，纯离屏 + stub store）。

覆盖 modules/rss_aggregator/sidebar_data.py 中 _RssSidebar 的：
- _sort_nodes：name（大小写不敏感）/ added（字符串日期）/ updated（空串 last_refresh 排最后）排序与 desc 翻转
- _apply_sort：index → (label, field, desc) 映射 + rss.sidebar.sort 写入 config
- current_filter()：kind → 过滤参数映射（feed/agg/unread/fav/torrent/all/None）
- reload()：节点构建（quick 4 类 + 父/子聚合 + 订阅源）、prev 选中恢复、config 快照回退、未读徽章计数

全 hermetic：offscreen、不建真 RssStore、不 GUI show、无网络。
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# 与既有 tests/test_rss_sidebar.py 相同的导入策略：走完整类（sidebar_actions 层含
# _on_sort_changed 等 __init__ 连接所需方法；dialogs 包随包导入，既有测试已证明离屏可用）。
from modules.rss_aggregator.sidebar_actions import _RssSidebar
from modules.rss_aggregator.sidebar import _SidebarNode


# ── 假 owner / store / page（不碰真 DB）──────────────────────────────

class FakeConfig(dict):
    """记录 set 调用的假配置（与 test_rss_sidebar.py 同款）。"""

    def __init__(self):
        super().__init__()
        self._data = {}

    def get(self, key, default=None):
        dct = {**self._data, **dict(self)}
        return dct.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def unset(self, key):
        self._data.pop(key, None)


class FakeCtx:
    def __init__(self):
        self.config = FakeConfig()


class StubStore:
    """list_sidebar / count_items 的假实现，不建真 RssStore。"""

    def __init__(self, feeds, aggregations, counts):
        self._feeds = feeds
        self._aggs = aggregations
        self._counts = counts

    def list_sidebar(self):
        return {"feeds": self._feeds, "aggregations": self._aggs}

    def count_items(self, unread_only=False, favorites_only=False, magnet_only=False):
        if unread_only:
            return self._counts["unread"]
        if favorites_only:
            return self._counts["fav"]
        if magnet_only:
            return self._counts["magnet"]
        return self._counts["all"]


class FakeOwner:
    def __init__(self, store):
        self.store = store
        self.context = FakeCtx()


class FakePage:
    """reload() 需要的 page 回调（on_sidebar_selection_changed 等）。"""

    def __init__(self):
        self.selection_changed_calls = 0

    def on_sidebar_selection_changed(self):
        self.selection_changed_calls += 1

    def _toggle_feed_section(self):
        pass


@pytest.fixture(autouse=True)
def _sidebar_cleanup():
    yield
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for widget in list(app.allWidgets()):
        if isinstance(widget, _RssSidebar):
            widget.close()
            widget.deleteLater()
    app.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, 0)


# ── 测试数据与构造辅助 ────────────────────────────────────────────────

def _stub_data():
    """fake list_sidebar 数据：2 启用源 + 1 停用源 + 1 父聚合 + 1 子聚合。"""
    feeds = [
        {"id": 1, "name": "站点A", "enabled": True, "icon": "", "unread": 3,
         "created_at": "2026-01-01", "last_refresh": "2026-01-02"},
        {"id": 2, "name": "站点B", "enabled": True, "icon": "", "unread": 0,
         "created_at": "2026-01-02", "last_refresh": ""},
        {"id": 3, "name": "停用站", "enabled": False, "icon": "", "unread": 9,
         "created_at": "2026-01-03", "last_refresh": "2026-01-04"},
    ]
    aggs = [
        {"id": 10, "name": "父聚合", "agg_type": "mixed", "parent_id": 0, "count": 5,
         "created_at": "2026-01-01", "last_refreshed": "2026-01-03"},
        {"id": 11, "name": "子聚合", "agg_type": "keyword", "parent_id": 10, "count": 2,
         "created_at": "2026-01-02", "last_refreshed": "2026-01-03"},
    ]
    counts = {"all": 100, "unread": 12, "fav": 5, "magnet": 7}
    return feeds, aggs, counts


def _build_sidebar():
    """构造完整 _RssSidebar（离屏），返回 (owner, page, sb)。"""
    feeds, aggs, counts = _stub_data()
    store = StubStore(feeds, aggs, counts)
    owner = FakeOwner(store)
    page = FakePage()
    sb = _RssSidebar(owner, page)
    return owner, page, sb


def _bare_sidebar(field="name", desc=False):
    """不跑 __init__ 的裸实例，仅用于 _sort_nodes / _apply_sort 纯逻辑测试。"""
    sb = _RssSidebar.__new__(_RssSidebar)
    sb._sort_field = field
    sb._sort_desc = desc
    return sb


def _node_data(sb):
    """返回 list 中每个 item 的 UserRole 数据（分组行为 None）。"""
    return [sb.list.item(i).data(QtCore.Qt.UserRole) for i in range(sb.list.count())]


def _find_row(sb, **match):
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and all(d.get(k) == v for k, v in match.items()):
            return i
    raise AssertionError("未找到匹配节点: %r" % (match,))


# ── 1. _sort_nodes：排序正确性 ────────────────────────────────────────

def test_sort_nodes_by_name_case_insensitive():
    sb = _bare_sidebar("name", False)
    nodes = [{"name": "Beta"}, {"name": "alpha"}, {"name": "Gamma"}]
    out = sb._sort_nodes(nodes)
    assert [n["name"] for n in out] == ["alpha", "Beta", "Gamma"]


def test_sort_nodes_by_name_desc():
    sb = _bare_sidebar("name", True)
    nodes = [{"name": "Beta"}, {"name": "alpha"}, {"name": "Gamma"}]
    out = sb._sort_nodes(nodes)
    assert [n["name"] for n in out] == ["Gamma", "Beta", "alpha"]


def test_sort_nodes_by_added_string_date():
    sb = _bare_sidebar("added", False)
    nodes = [
        {"name": "b", "created_at": "2026-01-02"},
        {"name": "a", "created_at": "2026-01-01"},
        {"name": "c", "created_at": "2026-01-03"},
    ]
    out = sb._sort_nodes(nodes)
    assert [n["name"] for n in out] == ["a", "b", "c"]


def test_sort_nodes_by_updated_empty_last_refresh_last():
    sb = _bare_sidebar("updated", False)
    nodes = [
        {"name": "b", "last_refresh": "2026-01-02"},
        {"name": "empty", "last_refresh": ""},
        {"name": "a", "last_refresh": "2026-01-01"},
    ]
    out = sb._sort_nodes(nodes)
    assert [n["name"] for n in out] == ["a", "b", "empty"]


def test_sort_nodes_by_updated_uses_last_refreshed_for_aggs():
    sb = _bare_sidebar("updated", False)
    nodes = [
        {"name": "agg2", "last_refreshed": "2026-01-02"},
        {"name": "agg1", "last_refreshed": "2026-01-01"},
        {"name": "none", "last_refreshed": ""},
    ]
    out = sb._sort_nodes(nodes)
    assert [n["name"] for n in out] == ["agg1", "agg2", "none"]


def test_sort_nodes_by_updated_desc_flips_nonempty_only():
    # desc 翻转：非空时间倒序在前；空串因 reverse=True 被翻到最前（记录现状行为）
    sb = _bare_sidebar("updated", True)
    nodes = [
        {"name": "b", "last_refresh": "2026-01-02"},
        {"name": "empty", "last_refresh": ""},
        {"name": "a", "last_refresh": "2026-01-01"},
    ]
    out = sb._sort_nodes(nodes)
    assert [n["name"] for n in out] == ["empty", "b", "a"]


# ── 2. _apply_sort：index → (field, desc) 映射 + config 写入 ──────────

def test_apply_sort_maps_index_and_writes_config():
    owner = FakeOwner(StubStore(*_stub_data()))
    sb = _RssSidebar.__new__(_RssSidebar)
    sb.owner = owner
    sb._apply_sort(2)  # ("名称↑", "name", False)
    assert (sb._sort_field, sb._sort_desc) == ("name", False)
    assert owner.context.config.get("rss.sidebar.sort") == 2


def test_apply_sort_all_options_match_sort_options():
    owner = FakeOwner(StubStore(*_stub_data()))
    sb = _RssSidebar.__new__(_RssSidebar)
    sb.owner = owner
    expected = [
        ("updated", True),
        ("updated", False),
        ("name", False),
        ("name", True),
        ("added", True),
        ("added", False),
    ]
    assert len(_RssSidebar.SORT_OPTIONS) == len(expected)
    for i, (field, desc) in enumerate(expected):
        sb._apply_sort(i)
        assert (sb._sort_field, sb._sort_desc) == (field, desc)
        assert owner.context.config.get("rss.sidebar.sort") == i


def test_apply_sort_invalid_index_ignored():
    owner = FakeOwner(StubStore(*_stub_data()))
    sb = _RssSidebar.__new__(_RssSidebar)
    sb.owner = owner
    sb._sort_field, sb._sort_desc = "name", False
    sb._apply_sort(-1)
    sb._apply_sort(99)
    assert (sb._sort_field, sb._sort_desc) == ("name", False)
    assert owner.context.config.get("rss.sidebar.sort") is None


# ── 3. current_filter()：kind → 过滤参数映射 ──────────────────────────

def _set_current(sb, data):
    sb.list.clear()
    item = QtWidgets.QListWidgetItem("")
    item.setData(QtCore.Qt.UserRole, data)
    sb.list.addItem(item)
    sb.list.setCurrentRow(0)


def test_current_filter_feed():
    _, _, sb = _build_sidebar()
    _set_current(sb, {"kind": "feed", "feed_id": 7, "name": "站点A"})
    assert sb.current_filter() == {"feed_ids": [7]}


def test_current_filter_agg():
    _, _, sb = _build_sidebar()
    _set_current(sb, {"kind": "agg", "agg_id": 3, "agg_type": "keyword", "name": "关键词聚合"})
    assert sb.current_filter() == {"agg_id": 3, "agg_type": "keyword"}


def test_current_filter_unread():
    _, _, sb = _build_sidebar()
    _set_current(sb, {"kind": "unread", "name": "未读"})
    assert sb.current_filter() == {"unread_only": True}


def test_current_filter_fav():
    _, _, sb = _build_sidebar()
    _set_current(sb, {"kind": "fav", "name": "收藏"})
    assert sb.current_filter() == {"favorites_only": True}


def test_current_filter_torrent():
    _, _, sb = _build_sidebar()
    _set_current(sb, {"kind": "torrent", "name": "磁链"})
    assert sb.current_filter() == {"type_magnet": True}


def test_current_filter_all_and_no_selection():
    _, _, sb = _build_sidebar()
    _set_current(sb, {"kind": "all", "name": "全部条目"})
    assert sb.current_filter() == {}
    sb.list.clear()  # 无选中 → {}
    assert sb.current_filter() == {}


# ── 4. reload()：节点构建 / 选中恢复 / config 快照回退 ────────────────

def test_reload_builds_nodes_order_and_indent():
    _, _, sb = _build_sidebar()
    sb.combo_sort.setCurrentIndex(2)  # 名称↑ → 触发 reload，按名称排序（默认"更新时间↓"会翻转空串）
    data = _node_data(sb)
    # 4 快捷 + 分组"手动聚合" + 父/子聚合 + 分组"订阅源" + 2 启用源 = 10 行
    assert len(data) == 10
    kinds = [d.get("kind") if d else "group" for d in data]
    assert kinds == ["all", "unread", "fav", "torrent", "group",
                     "agg", "agg", "group", "feed", "feed"]
    # 父聚合在前、子聚合紧跟且 parent_id 指向父
    aggs = [d for d in data if d and d.get("kind") == "agg"]
    assert [a["agg_id"] for a in aggs] == [10, 11]
    assert aggs[0]["parent_id"] == 0
    assert aggs[1]["parent_id"] == 10
    # 停用源不出现
    feeds = [d for d in data if d and d.get("kind") == "feed"]
    assert [f["feed_id"] for f in feeds] == [1, 2]
    # 子聚合 node widget 带 indent 前缀（·）
    child_item = sb.list.item(_find_row(sb, kind="agg", agg_id=11))
    child_w = sb.list.itemWidget(child_item)
    assert isinstance(child_w, _SidebarNode)
    assert child_w.name_lb.text().startswith("· ")
    # 父聚合无 indent 前缀
    parent_item = sb.list.item(_find_row(sb, kind="agg", agg_id=10))
    parent_w = sb.list.itemWidget(parent_item)
    assert not parent_w.name_lb.text().startswith("· ")


def test_reload_unread_badges():
    _, _, sb = _build_sidebar()
    sb.reload()
    # 快捷"未读"节点计数来自 store.count_items(unread_only=True)
    unread_item = sb.list.item(_find_row(sb, kind="unread"))
    unread_w = sb.list.itemWidget(unread_item)
    assert unread_w.count_lb is not None
    assert unread_w.count_lb.text() == "12"
    # 订阅源未读徽章：站点A=3 有徽章；站点B=0 → None 无徽章
    feed_widgets = {}
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "feed":
            feed_widgets[d["feed_id"]] = sb.list.itemWidget(sb.list.item(i))
    assert feed_widgets[1].count_lb is not None
    assert feed_widgets[1].count_lb.text() == "3"
    assert feed_widgets[2].count_lb is None


def test_reload_feed_icon_fallback_globe():
    # feed 无 icon（""）→ 回退 GLOBE 图标，badge 有非空 pixmap
    _, _, sb = _build_sidebar()
    sb.reload()
    feed_item = sb.list.item(_find_row(sb, kind="feed", feed_id=1))
    w = sb.list.itemWidget(feed_item)
    pm = w.badge.pixmap()
    assert pm is not None and not pm.isNull()


def test_reload_restores_prev_feed_selection():
    _, _, sb = _build_sidebar()
    sb.reload()
    sb.list.setCurrentRow(_find_row(sb, kind="feed", feed_id=1))
    sb.reload()
    cur = sb.current_data()
    assert cur.get("kind") == "feed"
    assert cur.get("feed_id") == 1


def test_reload_restores_prev_agg_selection():
    _, _, sb = _build_sidebar()
    sb.reload()
    sb.list.setCurrentRow(_find_row(sb, kind="agg", agg_id=11))
    sb.reload()
    cur = sb.current_data()
    assert cur.get("kind") == "agg"
    assert cur.get("agg_id") == 11


def test_reload_config_snapshot_restores_agg():
    owner, _, sb = _build_sidebar()
    sb.reload()
    sb.list.setCurrentRow(-1)  # 清空选中 → prev=None
    owner.context.config.set("rss.sidebar.kind", "agg")
    owner.context.config.set("rss.sidebar.agg_id", 11)
    sb.reload(reselect=True)
    cur = sb.current_data()
    assert cur.get("kind") == "agg"
    assert cur.get("agg_id") == 11


def test_reload_config_snapshot_restores_feed():
    owner, _, sb = _build_sidebar()
    sb.reload()
    sb.list.setCurrentRow(-1)
    owner.context.config.set("rss.sidebar.kind", "feed")
    owner.context.config.set("rss.sidebar.feed_id", 2)
    sb.reload(reselect=True)
    cur = sb.current_data()
    assert cur.get("kind") == "feed"
    assert cur.get("feed_id") == 2


def test_reload_persists_sort_state():
    owner, _, sb = _build_sidebar()
    sb.reload()
    # 切到 名称↑（index 2）→ _on_sort_changed → _apply_sort + reload
    sb.combo_sort.setCurrentIndex(2)
    assert (sb._sort_field, sb._sort_desc) == ("name", False)
    assert owner.context.config.get("rss.sidebar.sort") == 2
    # 再次 reload：combo 选中与排序状态保持
    sb.reload()
    assert sb.combo_sort.currentIndex() == 2
    assert (sb._sort_field, sb._sort_desc) == ("name", False)
    assert owner.context.config.get("rss.sidebar.sort") == 2


# ── 聚合节点计数 k 格式化 ─────────────────────────────────────────────


def _build_sidebar_with_agg_count(count):
    """构造侧栏，首个聚合节点使用指定 count 值。"""
    feeds = [
        {"id": 1, "name": "站点A", "enabled": True, "icon": "", "unread": 3,
         "created_at": "2026-01-01", "last_refresh": "2026-01-02"},
    ]
    aggs = [
        {"id": 10, "name": "测试聚合", "agg_type": "mixed", "parent_id": 0,
         "count": count, "created_at": "2026-01-01", "last_refreshed": "2026-01-03"},
    ]
    counts = {"all": 100, "unread": 12, "fav": 5, "magnet": 7}
    store = StubStore(feeds, aggs, counts)
    owner = FakeOwner(store)
    page = FakePage()
    sb = _RssSidebar(owner, page)
    sb.reload()
    return sb


@pytest.mark.parametrize("count,expected", [
    (4022, "4.0k"),   # 4022/1000=4.022 → "%.1f" rounds to "4.0" → buggy strips ".0k" → "4.0" (missing k); fixed keeps "4.0k"
    (4000, "4k"),     # 4000/1000=4.0 → "4.0k" → buggy strips to "4.0"; should be "4k"
    (4282, "4.3k"),   # 4282/1000=4.282 → "4.3k" ← regression guard (already works)
    (999, "999"),     # <1000 → no k suffix ← regression guard (already works)
    (1000, "1k"),     # 1000/1000=1.0 → "1.0k" → buggy strips to "1.0"; should be "1k"
])
def test_count_k_format(count, expected):
    sb = _build_sidebar_with_agg_count(count)
    agg_item = sb.list.item(_find_row(sb, kind="agg", agg_id=10))
    agg_w = sb.list.itemWidget(agg_item)
    assert isinstance(agg_w, _SidebarNode)
    assert agg_w.count_lb is not None
    assert agg_w.count_lb.text() == expected


def test_count_none_hides_label():
    """count=None → _SidebarNode.count_lb is None（无计数标签）。"""
    node = _SidebarNode("测试", badge_char="◉", count=None)
    assert node.count_lb is None
    node.close()
    node.deleteLater()