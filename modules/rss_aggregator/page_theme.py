"""RSS 页面：主题切换动态刷新 QSS。"""

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .page_toolbar import _RssPageWidget
from .styles import _btn_style, _sidebar_qss
from .text_utils import _rss_colors


class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _migrated_btn_qss(self):
        """迁移进标题栏后的紧凑按钮 QSS（透明底 + 主题文字色）。

        与主窗口 _TextTitleBarButton 一致：无浅色底、文字随明暗主题、不截断。
        主题切换时由 _apply_theme 复用，保证迁移后按钮随主题刷新。
        """
        c = _rss_colors()
        return (
            "QPushButton {{ background: transparent; border: none; padding: 0 8px; "
            "color: {text}; font-size: 13px; }}"
            "QPushButton:hover {{ background: {control_bg_hover}; }}"
            "QPushButton:pressed {{ background: rgba(0,0,0,0.10); }}"
        ).format(**c)

    def _apply_theme(self):
        """主题切换后重设动态 QSS（不重建控件，幂等）。"""
        c = _rss_colors()
        self.tool_bar.setStyleSheet(
            ("QFrame#rssToolBar {{ background: {ctrl_bg}; border: 1px solid {ctrl_border}; "
             "border-radius: 8px; }}").format(**c))
        for name, attr in (("rssSideCol", "_side_col"), ("rssListCol", "_list_col"),
                           ("rssPreviewCol", "_preview_col")):
            getattr(self, attr).setStyleSheet(
                f"QFrame#{name} {{ background: {c['panel']}; border: 1px solid {c['border']}; "
                f"border-radius: 12px; padding: 12px; }}")
        self.item_list.setStyleSheet(
            ("QListWidget {{ background: transparent; border: none; }}"
             "QListWidget::item {{ margin: 1px 3px; padding: 3px 5px; border-radius: 6px; "
             "border: 1px solid transparent; }}"
             "QListWidget::item:hover {{ background: {row_hover}; "
             "border: 1px solid {border_strong}; }}"
             "QListWidget::item:selected {{ background: {row_selected}; "
             "border: 1px solid {accent}; }}").format(**c))
        self._summary_title.setStyleSheet(
            f"QLabel {{ font-size: 14px; font-weight: 700; background: transparent; color: {c['text']}; }}")
        self._summary_meta.setStyleSheet(
            f"QLabel {{ color: {c['text_secondary']}; font-size: 12px; background: transparent; line-height: 1.6; }}")
        self._summary_desc.setStyleSheet(
            f"QLabel {{ font-size: 12.5px; background: transparent; color: {c['text']}; line-height: 1.7; }}")
        self._preview_placeholder.setStyleSheet(
            f"color: {c['text_faint']}; font-size: 13px; padding: 20px;")
        self._refresh_status_chip()
        self._sidebar.setStyleSheet(_sidebar_qss())
        self._globe.setStyleSheet(
            f"background: {c['accent_bg']}; color: {c['accent']}; "
            f"border: 1px solid {c['accent']}; border-radius: 8px; font-size: 14px;")
        self._lbl_title.setStyleSheet(
            f"color: {c['text_primary']}; font-size: 16px; font-weight: 700;")
        self.lb_page.setStyleSheet(f"color: {c['text_secondary']}; padding: 0 4px;")
        self.lb_total.setStyleSheet(f"color: {c['text_secondary']}; padding-right: 6px;")
        self._sep_line.setStyleSheet(f"background: {c['border']};")
        for b in (self.btn_prev, self.btn_next):
            b.setStyleSheet(_btn_style(min_width=0, padding="3px 14px", radius=6))
        for grip in (self._grip1, self._grip2):
            grip.setStyleSheet(
                "QFrame { background: transparent; }"
                f"QFrame:hover {{ background: {c['accent']}; }}")
            line = getattr(grip, "_line", None)
            if line is not None:
                line.setStyleSheet(f"background: {c['border']}; border-radius: 2px;")
        if getattr(self, "_title_bar_migrated", False):
            qss = self._migrated_btn_qss()
            for b in (self.btn_date_filter, self.btn_filter, self.btn_read_ops,
                      self.btn_batch_ops, self.btn_thumb):
                b.setStyleSheet(qss)
            self._search_wg.setStyleSheet(
                "QFrame#rssSearchBox { background: transparent; border: none; }")
        else:
            for b in (self.btn_date_filter, self.btn_filter, self.btn_read_ops,
                      self.btn_batch_ops, self.btn_thumb):
                b.setStyleSheet(_btn_style(min_width=0, padding="6px 14px", radius=8))
            self._search_wg.setStyleSheet(
                f"QFrame#rssSearchBox {{ background: {c['ctrl_bg']}; "
                f"border: 1px solid {c['ctrl_border']}; border-radius: 9px; }}")

    def _refresh_status_chip(self):
        """按当前胶囊文字重设状态胶囊配色（磁链/文章）。"""
        text = self._summary_status.text()
        if not text:
            return
        c = _rss_colors()
        is_torrent = text == "磁链"
        if c["dark"]:
            chip_bg = "rgba(255,107,142,0.16)" if is_torrent else "rgba(37,205,150,0.16)"
            chip_fg = "#ff9ab0" if is_torrent else "#7fe0c0"
        else:
            chip_bg = "#fce8e6" if is_torrent else "#e6f4ea"
            chip_fg = "#c5221f" if is_torrent else "#137333"
        self._summary_status.setStyleSheet(
            f"QLabel {{ font-size: 11px; padding: 3px 10px; border-radius: 14px; "
            f"font-weight: 600; background: {chip_bg}; color: {chip_fg}; }}")