"""RSS 页面：主题切换动态刷新 QSS。"""

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

_, QtCore, QtGui, QtWidgets = import_qt()

from .page_toolbar import _RssPageWidget
from .styles import _btn_style, _sidebar_qss
from .text_utils import rss_palette, rss_style_vars


def _migrated_btn_qss(vars_):
    """迁移进标题栏后的紧凑按钮 QSS（主题感知：半透明底 + 1px 边框）。

    纯函数：vars_ 为 rss_style_vars() 合并字典（颜色与尺寸令牌同源），
    便于测试直接断言输出。与 _btn_style 视觉一致：hover 提亮、pressed
    加深、checked 强调、disabled 淡化。右 padding 26px 为 DropDownPushButton
    箭头让位（箭头自绘在 width()-22 处），不可省略。
    """
    return (
        "QPushButton {{ background: {rss_control_bg}; border: 1px solid {rss_control_border}; "
        "border-radius: {rss_radius_compact}px; text-align: left; "
        "padding: 0 26px 0 8px; "
        "color: {rss_text}; font-size: {font_size_md}px; }}"
        "QPushButton:hover {{ background: {rss_control_bg_hover}; border-color: {rss_control_border_hover}; }}"
        "QPushButton:pressed {{ background: {overlay_pressed}; }}"
        "QPushButton:checked {{ background: {rss_accent_bg}; border-color: {rss_accent}; color: {rss_accent}; }}"
        "QPushButton:disabled {{ color: {rss_text_faint}; background: transparent; border-color: {rss_border}; }}"
    ).format(**vars_)


class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _migrated_btn_qss(self):
        """迁移进标题栏后的紧凑按钮 QSS（主题感知：半透明底 + 1px 边框）。

        与主窗口 _TextTitleBarButton 一致：文字随明暗主题、不截断。
        主题切换时由 _apply_theme 复用，保证迁移后按钮随主题刷新。
        """
        return _migrated_btn_qss(rss_style_vars())

    def _apply_theme(self):
        """主题切换后重设动态 QSS（不重建控件，幂等）。"""
        c = rss_style_vars()
        self.tool_bar.setStyleSheet(
            ("QFrame#rssToolBar {{ background: {rss_ctrl_bg}; border: 1px solid {rss_ctrl_border}; "
             "border-radius: {rss_radius_md}px; }}").format(**c))
        for name, attr in (("rssSideCol", "_side_col"), ("rssListCol", "_list_col"),
                           ("rssPreviewCol", "_preview_col")):
            getattr(self, attr).setStyleSheet(
                f"QFrame#{name} {{ background: {c['rss_panel']}; border: 1px solid {c['rss_border']}; "
                f"border-radius: {c['rss_radius_2xl']}px; padding: {c['rss_card_padding']}; }}")
        self.item_list.setStyleSheet(
            ("QListWidget {{ background: transparent; border: none; }}"
             "QListWidget::item {{ margin: {rss_row_margin}; padding: {rss_item_padding}; "
             "border-radius: {rss_radius_sm}px; "
             "border: 1px solid transparent; }}"
             "QListWidget::item:hover {{ background: {rss_row_hover}; "
             "border: 1px solid {rss_border_strong}; }}"
             "QListWidget::item:selected {{ background: {rss_row_selected}; "
             "border: 1px solid {rss_accent}; }}").format(**c))
        self._summary_title.setStyleSheet(
            f"QLabel {{ font-size: {c['rss_font_lg']}px; font-weight: 700; background: transparent; color: {c['rss_text']}; }}")
        self._summary_meta.setStyleSheet(
            f"QLabel {{ color: {c['rss_text_secondary']}; font-size: {c['rss_font_md']}px; "
            f"background: transparent; line-height: 1.6; }}")
        self._summary_desc.setStyleSheet(
            f"QLabel {{ font-size: 12.5px; background: transparent; color: {c['rss_text']}; line-height: 1.7; }}")
        self._preview_placeholder.setStyleSheet(
            f"color: {c['rss_text_faint']}; font-size: {c['font_size_md']}px; padding: {c['rss_empty_padding']};")
        self._refresh_status_chip()
        self._sidebar.setStyleSheet(_sidebar_qss())
        self._globe.setStyleSheet(
            f"background: {c['rss_accent_bg']}; color: {c['rss_accent']}; "
            f"border: 1px solid {c['rss_accent']}; border-radius: {c['rss_radius_md']}px; "
            f"font-size: {c['rss_font_lg']}px;")
        self._lbl_title.setStyleSheet(
            f"color: {c['rss_text_primary']}; font-size: {c['font_size_lg']}px; font-weight: 700;")
        self.lb_page.setStyleSheet(f"color: {c['rss_text_secondary']}; padding: 0 4px;")
        self.lb_total.setStyleSheet(f"color: {c['rss_text_secondary']}; padding-right: 6px;")
        self._sep_line.setStyleSheet(f"background: {c['rss_border']};")
        for b in (self.btn_prev, self.btn_next):
            b.setStyleSheet(_btn_style(min_width=0, padding="3px 14px", radius=6))
        for grip in (self._grip1, self._grip2):
            grip.setStyleSheet(
                "QFrame { background: transparent; }"
                f"QFrame:hover {{ background: {c['rss_accent']}; }}")
            line = getattr(grip, "_line", None)
            if line is not None:
                line.setStyleSheet(f"background: {c['rss_border']}; border-radius: {c['rss_radius_xs']}px;")
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
                f"QFrame#rssSearchBox {{ background: {c['rss_ctrl_bg']}; "
                f"border: 1px solid {c['rss_ctrl_border']}; border-radius: {c['rss_radius_lg']}px; }}")

    def _refresh_status_chip(self):
        """按当前胶囊文字重设状态胶囊配色（磁链/文章）。"""
        text = self._summary_status.text()
        if not text:
            return
        c = rss_palette()
        is_torrent = text == "磁链"
        chip_bg = c["rss_chip_torrent_bg" if is_torrent else "rss_chip_article_bg"]
        chip_fg = c["rss_chip_torrent_fg" if is_torrent else "rss_chip_article_fg"]
        self._summary_status.setStyleSheet(
            f"QLabel {{ font-size: {sizing()['rss_font_sm']}px; padding: {sizing()['rss_pill_padding']}; "
            f"border-radius: {sizing()['rss_radius_3xl']}px; "
            f"font-weight: 600; background: {chip_bg}; color: {chip_fg}; }}")