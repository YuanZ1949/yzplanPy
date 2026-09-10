"""blog 独立页面：_make_page_widget（Markdown 原文编辑，不渲染预览）。"""
from .store import add_post, update_post, delete_post, list_posts, get_post


def _make_page_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)

    toolbar = QtWidgets.QHBoxLayout()
    btn_new = PrimaryPushButton("新建")
    btn_save = PushButton("保存")
    btn_del = PushButton("删除")
    toolbar.addWidget(btn_new)
    toolbar.addWidget(btn_save)
    toolbar.addWidget(btn_del)
    toolbar.addStretch(1)
    lay.addLayout(toolbar)

    splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    list_widget = QtWidgets.QListWidget()
    list_widget.setMinimumWidth(200)
    splitter.addWidget(list_widget)

    editor_panel = QtWidgets.QWidget()
    editor_lay = QtWidgets.QVBoxLayout(editor_panel)
    editor_lay.setContentsMargins(0, 0, 0, 0)
    editor_lay.setSpacing(6)
    title_input = QtWidgets.QLineEdit()
    title_input.setPlaceholderText("文章标题...")
    editor_lay.addWidget(title_input)
    content_input = QtWidgets.QPlainTextEdit()
    content_input.setPlaceholderText("Markdown 正文（原文保存，不渲染预览）...")
    editor_lay.addWidget(content_input, 1)
    splitter.addWidget(editor_panel)
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 3)

    # 恢复上次保存的分割位置，并在用户拖动时记住（blog.splitter_state）
    _state_key = "blog.splitter_state"
    _saved = owner.context.config.get(_state_key)
    if _saved:
        _ba = QtCore.QByteArray.fromBase64(_saved.encode("ascii"))
        splitter.restoreState(_ba)
    splitter.splitterMoved.connect(lambda *_: owner.context.config.set(
        _state_key, splitter.saveState().toBase64().data().decode("ascii")))

    lay.addWidget(splitter, 1)

    status_bar = BodyLabel("")
    status_bar.setStyleSheet("color: #888;")
    lay.addWidget(status_bar)

    current_id = {"id": None}

    def refresh_list(select_id=None):
        list_widget.clear()
        for p in list_posts():
            item = QtWidgets.QListWidgetItem(f"{p['title']}\n{p['updated_at']}")
            item.setData(QtCore.Qt.UserRole, p["id"])
            list_widget.addItem(item)
        if select_id is not None:
            for i in range(list_widget.count()):
                if list_widget.item(i).data(QtCore.Qt.UserRole) == select_id:
                    list_widget.setCurrentRow(i)
                    break

    def load_post(post_id):
        p = get_post(post_id)
        if p is None:
            return
        current_id["id"] = post_id
        title_input.setText(p["title"])
        content_input.setPlainText(p["content"])
        status_bar.setText(f"已加载：{p['title']}")

    def on_list_click(item):
        post_id = item.data(QtCore.Qt.UserRole)
        if post_id is not None:
            load_post(post_id)

    def on_new():
        current_id["id"] = None
        title_input.clear()
        content_input.clear()
        list_widget.clearSelection()
        status_bar.setText("新建文章：填写标题与内容后点击保存")

    def on_save():
        title = title_input.text().strip()
        if not title:
            status_bar.setText("保存失败：标题不能为空")
            return
        content = content_input.toPlainText()
        try:
            if current_id["id"] is None:
                pid = add_post(title, content)
                status_bar.setText(f"已新建：{title}")
            else:
                update_post(current_id["id"], title=title, content=content)
                pid = current_id["id"]
                status_bar.setText(f"已保存：{title}")
        except ValueError as e:
            status_bar.setText(f"保存失败：{e}")
            return
        refresh_list(select_id=pid)

    def on_delete():
        pid = current_id["id"]
        if pid is None:
            status_bar.setText("请先选择要删除的文章")
            return
        delete_post(pid)
        current_id["id"] = None
        title_input.clear()
        content_input.clear()
        refresh_list()
        status_bar.setText("已删除")

    list_widget.itemClicked.connect(on_list_click)
    btn_new.clicked.connect(on_new)
    btn_save.clicked.connect(on_save)
    btn_del.clicked.connect(on_delete)

    refresh_list()
    return w