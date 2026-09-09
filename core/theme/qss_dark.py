"""深色全局 QSS。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

def _apply_dark_sheet(acrylic):
    bg_alpha = "rgba(30,30,30,0.65)" if acrylic else "rgba(30,30,30,0.92)"

    sheet = f"""
    QWidget#modules_tab, QWidget#home_tab, QWidget#settings_tab, QWidget#about_tab {{
        background: transparent;
    }}

    QLabel {{
        background: transparent;
    }}

    QListWidget {{
        background: {bg_alpha};
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-radius: 6px;
    }}
    QListWidget::item:selected {{
        background: rgba(0,120,215,0.35);
    }}
    QListWidget::item:hover {{
        background: rgba(255,255,255,0.06);
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
        background: rgba(255,255,255,0.12);
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(255,255,255,0.22);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QPushButton {{
        background: rgba(60,60,60,0.80);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 6px;
        padding: 5px 14px;
        min-height: 30px;
        color: #e0e0e0;
    }}
    QPushButton:hover {{
        background: rgba(80,80,80,0.90);
        border: 1px solid rgba(255,255,255,0.15);
    }}
    QPushButton:pressed {{
        background: rgba(45,45,45,0.95);
    }}

    QLineEdit {{
        background: rgba(40,40,40,0.85);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 6px;
        padding: 5px 10px;
        color: #e8e8e8;
        selection-background-color: rgba(0,120,215,0.4);
    }}
    QLineEdit:focus {{
        border: 1px solid rgba(0,120,215,0.6);
    }}

    QComboBox {{
        background: rgba(50,50,50,0.85);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 6px;
        padding: 4px 10px;
        color: #e0e0e0;
    }}

    QFrame {{
        background: transparent;
    }}

    QCheckBox {{
        background: transparent;
        color: #e0e0e0;
    }}
    QCheckBox:disabled {{
        color: rgba(255,255,255,0.35);
    }}

    QToolButton {{
        background: transparent;
        border: none;
        padding: 0 8px;
    }}

    QPlainTextEdit, QTextEdit {{
        background: rgba(40,40,40,0.85);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 6px;
        padding: 5px 10px;
        color: #e8e8e8;
        selection-background-color: rgba(0,120,215,0.4);
    }}
    QPlainTextEdit:focus, QTextEdit:focus {{
        border: 1px solid rgba(0,120,215,0.6);
    }}

    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid rgba(255,255,255,0.45);
        border-radius: 3px;
        background: transparent;
    }}
    QCheckBox::indicator:hover {{
        border: 1px solid rgba(0,120,215,0.7);
        background: rgba(0,120,215,0.12);
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
        border: 1px solid rgba(255,255,255,0.15);
        background: transparent;
    }}

    QTableWidget {{
        background: transparent;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
    }}
    QTableWidget::item {{
        border: none;
        padding: 2px 4px;
    }}
    QHeaderView::section {{
        background: transparent;
        border: none;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        padding: 4px 8px;
    }}

    QMenu {{
        background: rgba(42,42,42,0.96);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
        color: #e0e0e0;
    }}
    QMenu::item:selected {{
        background: rgba(0,120,215,0.35);
    }}
    QMenu::separator {{
        height: 1px;
        background: rgba(255,255,255,0.08);
        margin: 4px 8px;
    }}

    QMessageBox {{
        background: rgba(36,36,36,0.95);
    }}

    QDialog {{
        background: rgba(36,36,36,0.95);
    }}

    QFileDialog {{
        background: rgba(36,36,36,0.95);
    }}
    """

    QtWidgets.QApplication.instance().setStyleSheet(sheet)
