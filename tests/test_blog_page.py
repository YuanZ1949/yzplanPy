"""Blog 页面测试：列表加载、编辑保存、新建、删除。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QListWidget, QLineEdit, QPlainTextEdit, QPushButton

import modules.blog.page as bp
import modules.blog.store as store


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _Owner:
    pass


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db = tmp_path / "app.db"
    monkeypatch.setattr(store, "DB_PATH", str(db))
    return db


@pytest.fixture
def page(tmp_db):
    app = _app()
    w = bp._make_page_widget(_Owner(), None)
    w.show()
    for _ in range(10):
        app.processEvents()
    yield w
    w.close()


def _find(w, cls):
    return w.findChild(cls)


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