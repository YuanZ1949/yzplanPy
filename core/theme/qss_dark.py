"""深色全局 QSS。"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import theme_palette, sizing
_, QtCore, QtGui, QtWidgets = import_qt()

def _apply_dark_sheet(acrylic):
    p = theme_palette(dark=True)
    sz = sizing()
    bg_alpha = p["qss_bg_acrylic"] if acrylic else p["bg_app"]

    sheet = f"""
    QWidget#modules_tab, QWidget#home_tab, QWidget#settings_tab, QWidget#about_tab {{
        background: transparent;
    }}

    QLabel {{
        background: transparent;
    }}

    QListWidget {{
        background: {bg_alpha};
        border: 1px solid {p["rss_border"]};
        border-radius: {sz["radius_lg"]}px;
        padding: {sz["qss_list_padding"]};
        outline: none;
    }}
    QListWidget::item {{
        padding: {sz["qss_list_item_padding"]};
        border-radius: {sz["radius_md"]}px;
    }}
    QListWidget::item:selected {{
        background: {p["qss_list_sel_bg"]};
    }}
    QListWidget::item:hover {{
        background: {p["bg_hover"]};
    }}

    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        width: {sz["qss_scrollbar_width"]}px;
        background: transparent;
    }}
    QScrollBar::handle:vertical {{
        min-height: {sz["input_height"]}px;
        background: {p["qss_scrollbar_bg"]};
        border-radius: {sz["radius_sm"]}px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p["qss_scrollbar_hover"]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: {sz["qss_scrollbar_line_height"]};
    }}

    QPushButton {{
        background: {p["qss_btn_bg"]};
        border: 1px solid {p["qss_btn_border"]};
        border-radius: {sz["radius_md"]}px;
        padding: {sz["qss_btn_padding"]};
        min-height: {sz["input_height"]}px;
        color: {p["qss_btn_text"]};
    }}
    QPushButton:hover {{
        background: {p["qss_btn_bg_hover"]};
        border: 1px solid {p["qss_btn_border_hover"]};
    }}
    QPushButton:pressed {{
        background: {p["qss_btn_bg_pressed"]};
    }}

    QLineEdit {{
        background: {p["qss_input_bg"]};
        border: 1px solid {p["border"]};
        border-radius: {sz["radius_md"]}px;
        padding: {sz["qss_input_padding"]};
        color: {p["qss_input_text"]};
        selection-background-color: {p["qss_selection_bg"]};
    }}
    QLineEdit:focus {{
        border: 1px solid {p["qss_focus_border"]};
    }}

    QComboBox {{
        background: {p["qss_combo_bg"]};
        border: 1px solid {p["border"]};
        border-radius: {sz["radius_md"]}px;
        padding: {sz["qss_combo_padding"]};
        color: {p["qss_btn_text"]};
    }}

    QFrame {{
        background: transparent;
    }}

    QCheckBox {{
        background: transparent;
        color: {p["qss_btn_text"]};
    }}
    QCheckBox:disabled {{
        color: {p["qss_checkbox_disabled"]};
    }}

    QToolButton {{
        background: transparent;
        border: none;
        padding: {sz["qss_toolbtn_padding"]};
    }}

    QPlainTextEdit, QTextEdit {{
        background: {p["qss_input_bg"]};
        border: 1px solid {p["border"]};
        border-radius: {sz["radius_md"]}px;
        padding: {sz["qss_input_padding"]};
        color: {p["qss_input_text"]};
        selection-background-color: {p["qss_selection_bg"]};
    }}
    QPlainTextEdit:focus, QTextEdit:focus {{
        border: 1px solid {p["qss_focus_border"]};
    }}

    QCheckBox::indicator {{
        width: {sz["qss_indicator_size"]}px;
        height: {sz["qss_indicator_size"]}px;
        border: 1px solid {p["qss_indicator_border"]};
        border-radius: {sz["qss_indicator_radius"]}px;
        background: transparent;
    }}
    QCheckBox::indicator:hover {{
        border: 1px solid {p["qss_indicator_hover_border"]};
        background: {p["qss_indicator_hover_bg"]};
    }}
    QCheckBox::indicator:checked {{
        background: {p["qss_indicator_checked_bg"]};
        border: 1px solid {p["qss_indicator_checked_border"]};
    }}
    QCheckBox::indicator:checked:hover {{
        background: {p["qss_indicator_checked_hover_bg"]};
        border: 1px solid {p["qss_indicator_checked_hover_border"]};
    }}
    QCheckBox::indicator:disabled {{
        border: 1px solid {p["qss_indicator_disabled_border"]};
        background: transparent;
    }}

    QTableWidget {{
        background: transparent;
        border: 1px solid {p["rss_border"]};
        border-radius: {sz["radius_lg"]}px;
    }}
    QTableWidget::item {{
        border: none;
        padding: {sz["qss_table_item_padding"]};
    }}
    QHeaderView::section {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {p["rss_border"]};
        padding: {sz["qss_header_padding"]};
    }}

    QMenu {{
        background: {p["qss_menu_bg"]};
        border: 1px solid {p["qss_menu_border"]};
        border-radius: {sz["radius_lg"]}px;
        padding: {sz["qss_menu_padding"]};
    }}
    QMenu::item {{
        padding: {sz["qss_menu_item_padding"]};
        border-radius: {sz["radius_sm"]}px;
        color: {p["qss_btn_text"]};
    }}
    QMenu::item:selected {{
        background: {p["qss_menu_sel_bg"]};
    }}
    QMenu::separator {{
        height: {sz["qss_sep_height"]};
        background: {p["rss_border"]};
        margin: {sz["qss_sep_margin"]};
    }}

    QMessageBox {{
        background: {p["qss_dialog_bg"]};
    }}

    QDialog {{
        background: {p["qss_dialog_bg"]};
    }}

    QFileDialog {{
        background: {p["qss_dialog_bg"]};
    }}
    """

    QtWidgets.QApplication.instance().setStyleSheet(sheet)
