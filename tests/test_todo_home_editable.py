"""todo_notes 主页「可编辑待办列表」行为测试。

背景（主页问题反馈）：
- 主页列表之前双击 = 切换完成状态（划掉），用户明确希望双击改为「编辑内容」
- 主页列表之前只显示标题 + 优先级/截止，完全不展示 content 字段

锁定的主页行为：
1. 双击列表项 → 打开 _TodoEditDialog 编辑该条（不再切换完成状态）
2. 编辑保存后 update_todo 落库 + 列表刷新同步
3. 列表项携带 content 预览数据（_ROLE_CONTENT），供 delegate 画预览行
4. 新增输入行、优先级/截止展示保留不回归
"""
import pytest
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from modules import todo_store as _ts


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _roles():
    from modules.todo_notes.home import _ROLE_CONTENT, _ROLE_PRIORITY
    return _ROLE_CONTENT, _ROLE_PRIORITY


class _Owner:
    """todo 主页只引用 owner._home_refresh（挂载刷新回调）。"""

    def __init__(self):
        self._home_refresh = None


def _make_home():
    from modules.todo_notes.home import _make_home_widget
    owner = _Owner()
    w = _make_home_widget(owner, None)
    w.resize(360, 320)
    w.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    return owner, w


def _list_widget(w):
    return w.findChildren(QtWidgets.QListWidget)[0]


def _add_todo(title, content="", **kw):
    return _ts.add_todo(title, content=content, **kw)


def _item_by_title(w, title):
    lw = _list_widget(w)
    for i in range(lw.count()):
        if lw.item(i).text().startswith(title):
            return lw.item(i)
    return None


# ── 1. content 预览数据 ─────────────────────────────────────────────

def test_home_list_item_carries_content_preview():
    """列表项应携带 content 预览（_ROLE_CONTENT），供 delegate 画第二行。

    回归：主页此前只存 id/priority，content 字段完全丢弃。
    """
    _app()
    _ROLE_CONTENT, _ROLE_PRIORITY = _roles()
    tid = _add_todo("__preview__", content="这是内容预览文本")
    try:
        _, w = _make_home()
        try:
            item = _item_by_title(w, "__preview__")
            assert item is not None, "新增待办应出现在主页列表"
            assert item.data(_ROLE_CONTENT) == "这是内容预览文本", \
                "列表项应保存 content 以供 delegate 预览"
        finally:
            w.close()
    finally:
        _ts.delete_todo(tid)


# ── 2. 双击 = 编辑，不再划掉 ────────────────────────────────────────

def test_double_click_opens_edit_dialog_not_toggle(monkeypatch):
    """双击列表项应打开 _TodoEditDialog（编辑内容），且不切换完成状态。

    回归：此前双击 = _toggle_done（划掉），用户明确改为编辑。
    """
    _app()
    tid = _add_todo("__dbl__", content="c")
    try:
        owner, w = _make_home()
        try:
            item = _item_by_title(w, "__dbl__")
            assert item is not None

            calls = []

            class _FakeDialog:
                def __init__(self, parent=None, todo=None):
                    self._todo = todo
                    self._accepted = True

                def exec(self):
                    return (QtWidgets.QDialog.Accepted if self._accepted
                            else QtWidgets.QDialog.Rejected)

                def get_data(self):
                    return {
                        "title": "__dbl_edited__",
                        "content": "新的内容",
                        "priority": 2,
                        "category": "",
                        "due_date": None,
                        "status_id": None,
                    }

            import modules.todo_notes.home as h
            monkeypatch.setattr(h, "_TodoEditDialog", _FakeDialog)
            calls.append("opened")

            lw = _list_widget(w)
            lw.itemDoubleClicked.emit(item)
            for _ in range(5):
                QtWidgets.QApplication.processEvents()

            assert calls, "双击应触发编辑对话框"
            todos = {t["id"]: t for t in _ts.get_todos()}
            assert todos[tid]["title"] == "__dbl_edited__", "编辑保存应更新标题"
            assert todos[tid]["content"] == "新的内容", "编辑保存应更新内容"
            assert todos[tid]["done"] == 0, "双击编辑不应切换完成状态"

            # 列表应刷新为新标题
            assert _item_by_title(w, "__dbl_edited__") is not None, \
                "编辑保存后列表应刷新显示新标题"
        finally:
            w.close()
    finally:
        _ts.delete_todo(tid)


def test_double_click_cancel_keeps_todo(monkeypatch):
    """编辑对话框取消（Rejected）→ 数据库不变。"""
    _app()
    tid = _add_todo("__cancel__", content="原内容")
    try:
        _, w = _make_home()
        try:
            item = _item_by_title(w, "__cancel__")
            assert item is not None

            class _FakeCancelDialog:
                def __init__(self, parent=None, todo=None):
                    pass

                def exec(self):
                    return QtWidgets.QDialog.Rejected

                def get_data(self):
                    pytest.fail("取消时不应调用 get_data")

            import modules.todo_notes.home as h
            monkeypatch.setattr(h, "_TodoEditDialog", _FakeCancelDialog)
            lw = _list_widget(w)
            lw.itemDoubleClicked.emit(item)
            for _ in range(5):
                QtWidgets.QApplication.processEvents()

            todos = {t["id"]: t for t in _ts.get_todos()}
            assert todos[tid]["title"] == "__cancel__", "取消编辑不应改标题"
            assert todos[tid]["content"] == "原内容", "取消编辑不应改内容"
        finally:
            w.close()
    finally:
        _ts.delete_todo(tid)


# ── 3. 功能保留不回归 ───────────────────────────────────────────────

def test_home_keeps_add_row_and_count(monkeypatch):
    """新增输入行与待办计数保留（改造不删既有功能）。"""
    _app()
    _ROLE_CONTENT, _ROLE_PRIORITY = _roles()
    tid = _add_todo("__keep__", content="k")
    try:
        _, w = _make_home()
        try:
            assert w.findChildren(QtWidgets.QLineEdit), "主页应保留新增输入行"
            labels = [lb.text() for lb in w.findChildren(QtWidgets.QLabel)]
            assert any("待办" in t for t in labels), "主页应保留待办计数徽标"
            item = _item_by_title(w, "__keep__")
            assert item is not None
            assert item.data(_ROLE_PRIORITY) == 1, "优先级数据应保留"
        finally:
            w.close()
    finally:
        _ts.delete_todo(tid)


def test_home_priority_and_due_still_appended():
    """标题后的 [N天后]/[今天截止] 等截止标注逻辑保留。"""
    _app()
    from datetime import datetime, timedelta
    due = (datetime.now().date() + timedelta(days=3)).isoformat()
    tid = _add_todo("__due__", content="c", due_date=due)
    try:
        _, w = _make_home()
        try:
            item = _item_by_title(w, "__due__")
            assert item is not None
            assert "[3天后]" in item.text(), \
                f"截止标注应保留在标题后，实际: {item.text()!r}"
        finally:
            w.close()
    finally:
        _ts.delete_todo(tid)