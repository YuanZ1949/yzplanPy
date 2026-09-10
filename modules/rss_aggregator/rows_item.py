"""RSS 条目行构建：_make_item_row。"""

import logging
import re

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .rows import _AutoRow, _ElideLabel, _pill_style
from .text_utils import _rss_colors
from ..rss_store import _is_magnet_or_torrent

logger = logging.getLogger("rss_aggregator")

_network_mgr = None


def _get_network_mgr():
    global _network_mgr
    if _network_mgr is None:
        from PySide6.QtNetwork import QNetworkAccessManager
        _network_mgr = QNetworkAccessManager()
    return _network_mgr


def _load_thumb_async(url, label):
    """异步加载缩略图：QNetworkAccessManager 非阻塞下载，完成后设置 40x40 pixmap。"""
    from PySide6.QtNetwork import QNetworkRequest
    req = QNetworkRequest(QtCore.QUrl(url))
    req.setTransferTimeout(5000)
    reply = _get_network_mgr().get(req)

    def _on_reply():
        try:
            if reply.error() == reply.NetworkError.NoError:
                data = reply.readAll()
                pixmap = QtGui.QPixmap()
                pixmap.loadFromData(data)
                if not pixmap.isNull():
                    label.setPixmap(pixmap.scaled(
                        40, 40, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
                else:
                    label.setText("IMG")
            else:
                label.setText("IMG")
        except RuntimeError:
            pass  # label 已随行销毁（列表刷新/窗口关闭）
        finally:
            reply.deleteLater()

    reply.finished.connect(_on_reply)


def _make_item_row(widget, it, on_open, show_thumbnail=False, checked=False):
    c = _rss_colors()
    tags = it["tags"] or ""
    is_read = bool(it.get("read"))
    is_fav = bool(it.get("favorite"))
    type_tag = "磁链" if _is_magnet_or_torrent(it["link"]) else "文章"

    row_widget = _AutoRow()
    row_widget.setStyleSheet(
        f"QWidget#rssItemRow {{ background: transparent; border: 1px solid transparent; }}"
        f"QWidget#rssItemRow:hover {{ background: {c['row_hover']}; "
        f"border: 1px solid {c['border_strong']}; border-radius: 6px; }}"
        f"QWidget#rssItemRow[selected=\"true\"] {{ background: {c['row_selected']}; "
        f"border: 1px solid {c['accent']}; border-radius: 6px; }}"
    )
    row_widget.setProperty("selected", False)
    row_layout = QtWidgets.QHBoxLayout(row_widget)
    row_layout.setContentsMargins(6, 2, 6, 2)
    row_layout.setSpacing(4)

    chk = QtWidgets.QCheckBox()
    chk.setChecked(checked)
    row_layout.addWidget(chk)

    # 未读圆点：未读高亮，已读淡出
    dot = QtWidgets.QLabel("●")
    dot.setFixedWidth(10)
    dot.setStyleSheet(
        f"QLabel {{ color: {c['dot_unread'] if not is_read else c['dot_read']}; "
        "font-size: 10px; }")
    row_layout.addWidget(dot)

    if is_fav:
        fav_label = QtWidgets.QLabel("★")
        fav_label.setStyleSheet(f"QLabel {{ color: {c['fav_color']}; font-size: 14px; }}")
        fav_label.setFixedWidth(16)
        row_layout.addWidget(fav_label)

    if show_thumbnail and it.get("image_url"):
        thumb = QtWidgets.QLabel()
        thumb.setFixedSize(40, 40)
        thumb.setStyleSheet("QLabel { background: #f0f0f0; border-radius: 4px; }")
        thumb.setAlignment(QtCore.Qt.AlignCenter)
        thumb.setText("...")
        row_layout.addWidget(thumb)
        url = it["image_url"]
        if url.startswith("http"):
            _load_thumb_async(url, thumb)
        else:
            pixmap = QtGui.QPixmap(url)
            if not pixmap.isNull():
                thumb.setPixmap(pixmap.scaled(
                    40, 40, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            else:
                thumb.setText("IMG")
        row_widget.bind_thumb(thumb)

    title_text = it["title"] or it["link"]
    title_btn = _ElideLabel(title_text)
    title_btn.setToolTip(title_text)
    if is_read:
        title_btn.setStyleSheet(
            f"QLabel {{ text-align: left; border: none; background: transparent; "
            f"color: {c['title_read']}; padding: 2px; }}"
            f"QLabel:hover {{ color: {c['text_secondary']}; }}"
        )
    else:
        title_btn.setStyleSheet(
            f"QLabel {{ text-align: left; border: none; background: transparent; color: {c['title_unread']}; "
            "font-weight: 600; padding: 2px; }"
            f"QLabel:hover {{ color: {c['accent']}; }}"
        )
    title_btn._rss_dot = dot
    title_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
    row_layout.addWidget(title_btn, 1)

    if tags:
        tag_label = QtWidgets.QLabel(tags)
        tag_label.setStyleSheet(_pill_style(c["pill_tag_bg"], c["pill_tag_fg"]))
        tag_label.setAlignment(QtCore.Qt.AlignCenter)
        row_layout.addWidget(tag_label)

    type_label = QtWidgets.QLabel(type_tag)
    if type_tag == "磁链":
        type_label.setStyleSheet(_pill_style(c["pill_torrent_bg"], c["pill_torrent_fg"]))
    else:
        type_label.setStyleSheet(_pill_style(c["pill_article_bg"], c["pill_article_fg"]))
    type_label.setAlignment(QtCore.Qt.AlignCenter)
    row_layout.addWidget(type_label)

    pub = (it.get("published") or "").strip()
    if len(pub) >= 16:
        pub = pub[5:16]
    elif not pub:
        pub = ""
    if pub:
        time_label = QtWidgets.QLabel(pub)
        time_label.setStyleSheet(
            f"QLabel {{ color: {c['text_faint']}; font-size: 10px; padding-right: 4px; }}")
        time_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        row_layout.addWidget(time_label)

    row_widget.bind_title(title_btn)
    return row_widget, title_btn, chk
