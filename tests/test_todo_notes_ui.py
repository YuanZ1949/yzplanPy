import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from ui.adaptive_table import make_adaptive_table
from modules import todo_notes as tn


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


class _Owner:
    _page_refresh = None


def _make_page():
    _app()
    win = QtWidgets.QWidget()
    win.resize(820, 600)
    page = tn._make_page_widget(_Owner(), win)
    lay = QtWidgets.QVBoxLayout(win)
    lay.addWidget(page)
    win.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    return win, page


def _find_table(win):
    return [c for c in win.findChildren(QtWidgets.QTableWidget)][0]


def test_page_builds_with_adaptive_and_delegate():
    win, page = _make_page()
    table = _find_table(win)
    # 所有列 Interactive（沿用自适应工具）
    for c in range(table.columnCount()):
        assert table.horizontalHeader().sectionResizeMode(c) == QtWidgets.QHeaderView.Interactive
    # 安装了自定义 delegate
    delegates = [d for d in table.findChildren(QtWidgets.QStyledItemDelegate)]
    assert any(isinstance(d, tn._TodoItemDelegate) for d in delegates)


def test_delegate_editor_types():
    win, page = _make_page()
    table = _find_table(win)
    delegate = tn._TodoItemDelegate(table)
    opt = QtWidgets.QStyleOptionViewItem()
    model = table.model()

    # 类别 / 优先级 / 状态 -> QComboBox
    for col in (2, 3, 5):
        ed = delegate.createEditor(table, opt, model.index(0, col))
        assert isinstance(ed, QtWidgets.QComboBox), f"col {col} should be combo"
        ed.deleteLater()

    # 标题 -> QLineEdit（默认编辑器）
    ed0 = delegate.createEditor(table, opt, model.index(0, 0))
    assert isinstance(ed0, QtWidgets.QLineEdit)


def test_row_height_and_content_noneditable():
    win, page = _make_page()
    table = _find_table(win)
    assert table.verticalHeader().defaultSectionSize() >= 28
    item = table.item(0, 1)  # 内容列
    if item is not None:
        assert not (item.flags() & QtCore.Qt.ItemIsEditable)
