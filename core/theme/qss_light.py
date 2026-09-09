"""浅色全局 QSS。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

def _apply_light_sheet(acrylic):
    bg_alpha = "rgba(245,245,245,0.65)" if acrylic else "rgba(245,245,245,0.92)"

    sheet = f"""
    QWidget#modules_tab, QWidget#home_tab, QWidget#settings_tab, QWidget#about_tab {{
        background: transparent;
    }}

    QLabel {{
        background: transparent;
    }}

    QListWidget {{
        background: {bg_alpha};
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 8px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-radius: 6px;
    }}
    QListWidget::item:selected {{
        background: rgba(0,120,215,0.25);
    }}
    QListWidget::item:hover {{
        background: rgba(0,0,0,0.04);
    }}

    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        width: 8px;
        background: transparent;
    }}
    QScrollBar::handle:vertical {{
        min-height: 30px;
        background: rgba(0,0,0,0.12);
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(0,0,0,0.22);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QPushButton {{
        background: rgba(240,240,240,0.90);
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 6px;
        padding: 5px 14px;
        min-height: 30px;
        color: #2c2c2c;
    }}
    QPushButton:hover {{
        background: rgba(230,230,230,0.95);
        border: 1px solid rgba(0,0,0,0.15);
    }}
    QPushButton:pressed {{
        background: rgba(210,210,210,0.95);
    }}

    QLineEdit {{
        background: rgba(255,255,255,0.85);
        border: 1px solid rgba(0,0,0,0.12);
        border-radius: 6px;
        padding: 5px 10px;
        color: #1a1a1a;
        selection-background-color: rgba(0,120,215,0.3);
    }}
    QLineEdit:focus {{
        border: 1px solid rgba(0,120,215,0.6);
    }}

    QComboBox {{
        background: rgba(255,255,255,0.85);
        border: 1px solid rgba(0,0,0,0.12);
        border-radius: 6px;
        padding: 4px 10px;
        color: #2c2c2c;
    }}

    QFrame {{
        background: transparent;
    }}

    QCheckBox {{
        background: transparent;
        color: #2c2c2c;
    }}
    QCheckBox:disabled {{
        color: rgba(0,0,0,0.35);
    }}

    QToolButton {{
        background: transparent;
        border: none;
        padding: 0 8px;
    }}

    QPlainTextEdit, QTextEdit {{
        background: rgba(255,255,255,0.85);
        border: 1px solid rgba(0,0,0,0.12);
        border-radius: 6px;
        padding: 5px 10px;
        color: #1a1a1a;
        selection-background-color: rgba(0,120,215,0.3);
    }}
    QPlainTextEdit:focus, QTextEdit:focus {{
        border: 1px solid rgba(0,120,215,0.6);
    }}

    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid rgba(0,0,0,0.45);
        border-radius: 3px;
        background: transparent;
    }}
    QCheckBox::indicator:hover {{
        border: 1px solid rgba(0,120,215,0.7);
        background: rgba(0,120,215,0.10);
    }}
    QCheckBox::indicator:checked {{
        background: rgba(0,120,215,0.85);
        border: 1px solid rgba(0,120,215,0.9);
    }}
    QCheckBox::indicator:checked:hover {{
        background: rgba(0,120,215,0.95);
        border: 1px solid rgba(0,120,215,1.0);
    }}
    QCheckBox::indicator:disabled {{
        border: 1px solid rgba(0,0,0,0.15);
        background: transparent;
    }}

    QTableWidget {{
        background: transparent;
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 8px;
    }}
    QTableWidget::item {{
        border: none;
        padding: 2px 4px;
    }}
    QHeaderView::section {{
        background: transparent;
        border: none;
        border-bottom: 1px solid rgba(0,0,0,0.08);
        padding: 4px 8px;
    }}

    QMenu {{
        background: rgba(252,252,252,0.96);
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
        color: #2c2c2c;
    }}
    QMenu::item:selected {{
        background: rgba(0,120,215,0.18);
    }}
    QMenu::separator {{
        height: 1px;
        background: rgba(0,0,0,0.08);
        margin: 4px 8px;
    }}

    QMessageBox {{
        background: rgba(252,252,252,0.95);
    }}

    QDialog {{
        background: rgba(252,252,252,0.95);
    }}

    QFileDialog {{
        background: rgba(252,252,252,0.95);
    }}
    """

    QtWidgets.QApplication.instance().setStyleSheet(sheet)
