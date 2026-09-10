"""Blog 页面测试：列表加载、编辑保存、新建、删除、splitter 布局记忆。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QListWidget, QLineEdit, QPlainTextEdit, QPushButton, QSplitter

import modules.blog.page as bp
import modules.blog.store as store
from core.config import AppConfig


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _Owner:
    context = None  # 测试注入 owner.context.config


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db = tmp_path / "app.db"
    monkeypatch.setattr(store, "DB_PATH", str(db))
    return db


def _pump():
    for _ in range(10):
        QApplication.processEvents()


@pytest.fixture
def page(tmp_db, tmp_path):
    app = _app()
    cfg = AppConfig(str(tmp_path / "settings.json"))
    owner = _Owner()
    owner.context = type("Ctx", (), {"config": cfg})()
    w = bp._make_page_widget(owner, None)
    w.show()
    _pump()
    yield w
    w.close()


def _find(w, cls):
    return w.findChild(cls)


def test_splitter_state_saved_on_drag(tmp_db, tmp_path):
    """移动分割条 → blog.splitter_state 写入配置。"""
    app = _app()
    cfg = AppConfig(str(tmp_path / "settings.json"))
    owner = _Owner()
    owner.context = type("Ctx", (), {"config": cfg})()
    w = bp._make_page_widget(owner, None)
    w.resize(900, 600)
    w.show()
    _pump()
    splitter = _find(w, QSplitter)
    assert splitter is not None
    splitter.setSizes([320, 560])
    # setSizes 不触发 splitterMoved（仅用户拖拽发射），这里手动发射模拟拖拽
    splitter.splitterMoved.emit(320, 1)
    _pump()
    assert cfg.get("blog.splitter_state"), "拖动分割条后应写入 blog.splitter_state"
    w.close()


def test_splitter_state_restored_on_reopen(tmp_db, tmp_path):
    """重建页面 → 分割位置按上次保存的尺寸恢复。"""
    app = _app()
    cfg = AppConfig(str(tmp_path / "settings.json"))
    owner = _Owner()
    owner.context = type("Ctx", (), {"config": cfg})()

    w1 = bp._make_page_widget(owner, None)
    w1.resize(900, 600)
    w1.show()
    _pump()
    splitter1 = _find(w1, QSplitter)
    splitter1.setSizes([320, 560])
    splitter1.splitterMoved.emit(320, 1)  # 模拟用户拖拽（setSizes 不发射该信号）
    _pump()
    w1.close()

    w2 = bp._make_page_widget(owner, None)
    w2.resize(900, 600)
    w2.show()
    _pump()
    try:
        splitter2 = _find(w2, QSplitter)
        sizes = splitter2.sizes()
        assert len(sizes) == 2
        # 恢复后列表侧约 320（允许布局/取整误差，但绝不能回到默认 1:3）
        assert 260 <= sizes[0] <= 380, f"splitter 列表侧宽度未恢复: {sizes}"
    finally:
        w2.close()


def _btn(page, text):
    for b in page.findChildren(QPushButton):
        if b.text() == text:
            return b
    return None


def _pump():
    for _ in range(10):
        QApplication.processEvents()


def test_page_builds_with_list_and_editor(page):
    assert _find(page, QListWidget) is not None
    assert _find(page, QLineEdit) is not None
    assert _find(page, QPlainTextEdit) is not None
    assert _btn(page, "新建") is not None
    assert _btn(page, "保存") is not None
    assert _btn(page, "删除") is not None


def test_new_save_load_roundtrip(page):
    title_input = _find(page, QLineEdit)
    content_input = _find(page, QPlainTextEdit)
    list_widget = _find(page, QListWidget)
    btn_new = _btn(page, "新建")
    btn_save = _btn(page, "保存")

    btn_new.click()
    title_input.setText("测试文章")
    content_input.setPlainText("# Markdown\n正文内容")
    btn_save.click()
    _pump()

    assert list_widget.count() == 1
    assert "测试文章" in list_widget.item(0).text()

    # 点击列表加载
    list_widget.itemClicked.emit(list_widget.item(0))
    assert title_input.text() == "测试文章"
    assert content_input.toPlainText() == "# Markdown\n正文内容"

    # 修改并保存
    content_input.setPlainText("更新后的内容")
    btn_save.click()
    _pump()
    posts = store.list_posts()
    assert len(posts) == 1
    assert posts[0]["title"] == "测试文章"
    assert posts[0]["content"] == "更新后的内容"


def test_empty_title_save_rejected(page):
    title_input = _find(page, QLineEdit)
    btn_save = _btn(page, "保存")
    title_input.setText("   ")
    btn_save.click()
    _pump()
    assert store.list_posts() == []


def test_delete_removes_post(page):
    title_input = _find(page, QLineEdit)
    content_input = _find(page, QPlainTextEdit)
    list_widget = _find(page, QListWidget)
    btn_new = _btn(page, "新建")
    btn_save = _btn(page, "保存")
    btn_del = _btn(page, "删除")

    btn_new.click()
    title_input.setText("待删文章")
    content_input.setPlainText("内容")
    btn_save.click()
    _pump()
    assert list_widget.count() == 1

    list_widget.itemClicked.emit(list_widget.item(0))
    btn_del.click()
    _pump()
    assert list_widget.count() == 0
    assert store.list_posts() == []
    assert title_input.text() == ""