"""RSS 侧栏：行构建与渲染（从 sidebar_data.reload() 抽取）。"""

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .sidebar import _SidebarNode
from .text_utils import _qf, _relative_time, rss_palette
from core.theme.tokens import sizing


def _build_rows(sb, data, feed_icon_fn):
    """构建并渲染侧栏行到 sb.list（group + node）。

    sb: _RssSidebar 实例（提供 _sort_nodes, list, _nodes, owner.store）
    data: store.list_sidebar() 返回的 dict
    feed_icon_fn: callable(feed) -> QIcon
    """
    rows = []  # ("group", title) 或 ("node", data, badge_char, icon, badge_bg, badge_fg, count)
    _fic = _qf()["FluentIcon"]
    c = rss_palette()
    badge = c.get("rss_badge") or {}

    def bcol(kind):
        b = badge.get(kind) or {}
        return b.get("bg") or "", b.get("fg") or ""

    store = sb.owner.store
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
    # 两级聚合：先父聚合(parent_id==0)，后跟随其子聚合(parent_id==父id)
    all_aggs = sb._sort_nodes(data["aggregations"])
    for a in all_aggs:
        if int(a.get("parent_id") or 0) != 0:
            continue
        bg, fg = bcol("agg")
        label = a["name"]
        hint_parts = []
        last = _relative_time(a.get("last_refreshed") or "")
        if last:
            hint_parts.append(last)
        children = [ch for ch in all_aggs
                    if int(ch.get("parent_id") or 0) == a["id"]]
        expand = ("▾" if a["id"] in sb._expanded else "▸") if children else None
        rows.append(("node", {"kind": "agg", "agg_id": a["id"],
                     "agg_type": a.get("agg_type"), "name": label,
                     "parent_id": int(a.get("parent_id") or 0),
                     "has_children": bool(children),
                     "expand": expand,
                     "created_at": a.get("created_at") or "", "last_refreshed": a.get("last_refreshed") or "",
                     "hint": " · ".join(hint_parts)},
                     None, _fic.FOLDER.icon(), bg, fg, a.get("count") or 0))
        if a["id"] in sb._expanded:
            for ch in children:
                ch_last = _relative_time(ch.get("last_refreshed") or "")
                rows.append(("node", {"kind": "agg", "agg_id": ch["id"],
                             "agg_type": ch.get("agg_type"), "name": ch["name"],
                             "parent_id": a["id"],
                             "created_at": ch.get("created_at") or "", "last_refreshed": ch.get("last_refreshed") or "",
                             "hint": ch_last},
                             None, _fic.FOLDER.icon(), bg, fg, ch.get("count") or 0, 1))

    rows.append(("group", "订阅源"))
    for f in sb._sort_nodes([x for x in data["feeds"] if x.get("enabled")]):
        bg, fg = bcol("feed")
        rows.append(("node", {"kind": "feed", "feed_id": f["id"], "name": f["name"],
                     "created_at": f.get("created_at") or "", "last_refresh": f.get("last_refresh") or ""},
                     None, feed_icon_fn(f), bg, fg, f.get("unread") or None))

    for row in rows:
        if row[0] == "group":
            item = QtWidgets.QListWidgetItem()
            item.setFlags(QtCore.Qt.NoItemFlags)
            sb.list.addItem(item)
            sb._nodes.append(item)
            lab = QtWidgets.QLabel(row[1])
            lab.setStyleSheet("color: {}; font-size: {}px;"
                              "padding: {}; background: transparent;".format(
                                  c["rss_text_faint"], sizing()["rss_font_sm"],
                                  sizing()["rss_sidebar_group_padding"]))
            lab.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            sb.list.setItemWidget(item, lab)
            item.setSizeHint(QtCore.QSize(0, max(sizing()["rss_sidebar_group_row_height"],
                                                  lab.sizeHint().height())))
            continue
        _, d, char, icon, bg, fg, cnt = row[:7]
        indent = row[7] if len(row) > 7 else 0
        item = QtWidgets.QListWidgetItem("")
        item.setData(QtCore.Qt.UserRole, d)
        sb.list.addItem(item)
        sb._nodes.append(item)
        node_w = _SidebarNode(
            d.get("name") or "", badge_char=char, icon=icon,
            badge_bg=bg, badge_fg=fg, count=cnt,
            count_color=c["rss_accent"] if d.get("kind") == "unread" else None,
            count_bold=d.get("kind") == "unread",
            indent=indent,
            hint=d.get("hint") or None,
            expand=d.get("expand"),
        )
        sb.list.setItemWidget(item, node_w)
        item.setSizeHint(QtCore.QSize(0, max(sizing()["rss_sidebar_node_row_height"],
                                              node_w.sizeHint().height())))
