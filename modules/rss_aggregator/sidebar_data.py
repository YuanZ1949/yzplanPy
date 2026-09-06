"""RSS 侧栏：排序/重载/查询数据。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .sidebar import _RssSidebar, _SidebarNode
from .text_utils import _qf, _rss_colors
from .utils import _decode_feed_icon

class _RssSidebar(_RssSidebar):

    # ── 数据加载与排序 ─────────────────────────────────────
    def _sort_nodes(self, nodes):
        field = self._sort_field
        desc = self._sort_desc

        def key(n):
            if field == "name":
                v = (n.get("name") or "").lower()
            elif field == "added":
                v = n.get("created_at") or ""
            else:  # updated（feeds.last_refresh / aggregations.last_refreshed）
                v = n.get("last_refresh") or n.get("last_refreshed") or ""
                return (v == "", v)
            return v

        return sorted(nodes, key=key, reverse=desc)

    def _apply_sort(self, index):
        cfg = self.owner.context.config
        if 0 <= index < len(self.SORT_OPTIONS):
            label, field, desc = self.SORT_OPTIONS[index]
            self._sort_field, self._sort_desc = field, desc
            cfg.set("rss.sidebar.sort", index)

    def reload(self, reselect=False):
        prev = self.current_data()
        self._apply_sort(self.combo_sort.currentIndex())
        self.list.blockSignals(True)
        self.list.clear()
        self._nodes = []
        data = self.owner.store.list_sidebar()
        cfg = self.owner.context.config

        def feed_icon(feed):
            icon = _decode_feed_icon(feed.get("icon") or "")
            if not icon or icon.isNull():
                return _qf()["FluentIcon"].GLOBE.icon()
            return icon

        rows = []  # ("group", title) 或 ("node", data, badge_char, icon, badge_bg, badge_fg, count)
        _fic = _qf()["FluentIcon"]
        c = _rss_colors()
        badge = c.get("badge") or {}

        def bcol(kind):
            b = badge.get(kind) or {}
            return b.get("bg") or "", b.get("fg") or ""

        store = self.owner.store
        try:
            n_all = store.count_items()
            n_unread = store.count_items(unread_only=True)
            n_fav = store.count_items(favorites_only=True)
            n_mag = store.count_items(magnet_only=True)
        except Exception:
            n_all = n_unread = n_fav = n_mag = 0

        quick = [
            ("all", {"kind": "all", "name": "全部条目", "created_at": "", "last_refresh": ""}, "◉", n_all),
            ("unread", {"kind": "unread", "name": "未读", "created_at": "", "last_refresh": ""}, "◎", n_unread),
            ("fav", {"kind": "fav", "name": "收藏", "created_at": "", "last_refresh": ""}, "★", n_fav),
            ("torrent", {"kind": "torrent", "name": "磁链", "created_at": "", "last_refresh": ""}, "⇣", n_mag),
        ]
        for kind, node, char, cnt in quick:
            bg, fg = bcol(kind)
            rows.append(("node", node, char, None, bg, fg, cnt if cnt else None))

        rows.append(("group", "手动聚合"))
        for a in self._sort_nodes(data["aggregations"]):
            bg, fg = bcol("agg")
            label = a["name"]
            rows.append(("node", {"kind": "agg", "agg_id": a["id"],
                         "agg_type": a.get("agg_type"), "name": label,
                         "created_at": a.get("created_at") or "", "last_refreshed": a.get("last_refreshed") or ""},
                         None, _fic.FOLDER.icon(), bg, fg, a.get("count") or 0))

        rows.append(("group", "订阅源"))
        for f in self._sort_nodes([x for x in data["feeds"] if x.get("enabled")]):
            bg, fg = bcol("feed")
            rows.append(("node", {"kind": "feed", "feed_id": f["id"], "name": f["name"],
                         "created_at": f.get("created_at") or "", "last_refresh": f.get("last_refresh") or ""},
                         None, feed_icon(f), bg, fg, f.get("unread") or None))

        for row in rows:
            if row[0] == "group":
                item = QtWidgets.QListWidgetItem()
                item.setFlags(QtCore.Qt.NoItemFlags)
                item.setSizeHint(QtCore.QSize(0, 24))
                self.list.addItem(item)
                self._nodes.append(item)
                lab = QtWidgets.QLabel(row[1])
                lab.setStyleSheet("color: {}; font-size: 11px;"
                                  "padding: 2px 10px 0 10px; background: transparent;".format(c["text_faint"]))
                self.list.setItemWidget(item, lab)
                continue
            _, d, char, icon, bg, fg, cnt = row
            item = QtWidgets.QListWidgetItem("")
            item.setData(QtCore.Qt.UserRole, d)
            item.setSizeHint(QtCore.QSize(0, 30))
            self.list.addItem(item)
            self._nodes.append(item)
            node_w = _SidebarNode(
                d.get("name") or "", badge_char=char, icon=icon,
                badge_bg=bg, badge_fg=fg, count=cnt,
                count_color=c["accent"] if d.get("kind") == "unread" else None,
                count_bold=d.get("kind") == "unread",
            )
            self.list.setItemWidget(item, node_w)

        # 恢复选中
        def _match(item):
            d = item.data(QtCore.Qt.UserRole)
            if not d or not prev:
                return False
            if d.get("kind") == prev.get("kind"):
                if d.get("kind") == "feed" and d.get("feed_id") == prev.get("feed_id"):
                    return True
                if d.get("kind") == "agg" and d.get("agg_id") == prev.get("agg_id"):
                    return True
                if d.get("kind") == "all":
                    return True
            return False

        restored = False
        if prev:
            for i in range(self.list.count()):
                if _match(self.list.item(i)):
                    self.list.setCurrentRow(i)
                    restored = True
                    break
        if restored:
            self.list.blockSignals(False)
            self.page.on_sidebar_selection_changed()
            return
        if not restored and reselect:
            snap = cfg.get("rss.sidebar.kind")
            if snap == "agg":
                aid = cfg.get("rss.sidebar.agg_id")
                for i in range(self.list.count()):
                    d = self.list.item(i).data(QtCore.Qt.UserRole)
                    if d and d.get("kind") == "agg" and d.get("agg_id") == aid:
                        self.list.setCurrentRow(i)
                        self.list.blockSignals(False)
                        self.page.on_sidebar_selection_changed()
                        return
            elif snap == "feed":
                fid = cfg.get("rss.sidebar.feed_id")
                for i in range(self.list.count()):
                    d = self.list.item(i).data(QtCore.Qt.UserRole)
                    if d and d.get("kind") == "feed" and d.get("feed_id") == fid:
                        self.list.setCurrentRow(i)
                        self.list.blockSignals(False)
                        self.page.on_sidebar_selection_changed()
                        return
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.page.on_sidebar_selection_changed()

    def current_data(self):
        item = self.list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def current_filter(self):
        d = self.current_data()
        if not d:
            return {}
        kind = d.get("kind")
        if kind == "feed":
            return {"feed_ids": [d.get("feed_id")]}
        if kind == "agg":
            return {"agg_id": d.get("agg_id"), "agg_type": d.get("agg_type")}
        if kind == "unread":
            return {"unread_only": True}
        if kind == "fav":
            return {"favorites_only": True}
        if kind == "torrent":
            return {"type_magnet": True}
        return {}
