"""Blog 数据层测试：在临时 DB 上验证建表与 CRUD 全链路。"""
import pytest

import modules.blog.store as store


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db = tmp_path / "app.db"
    monkeypatch.setattr(store, "DB_PATH", str(db))
    return db


def test_create_table_on_first_call(tmp_db):
    assert not tmp_db.exists()
    store._get_conn()
    assert tmp_db.exists()
    conn = store._get_conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(blog_posts)").fetchall()]
    conn.close()
    assert cols == ["id", "title", "content", "created_at", "updated_at"]


def test_add_list_get_roundtrip(tmp_db):
    pid = store.add_post("第一篇", "## 标题\n正文内容")
    posts = store.list_posts()
    assert len(posts) == 1
    assert posts[0]["id"] == pid
    assert posts[0]["title"] == "第一篇"
    assert posts[0]["content"] == "## 标题\n正文内容"
    assert posts[0]["created_at"] == posts[0]["updated_at"]
    got = store.get_post(pid)
    assert got == posts[0]


def test_add_empty_title_raises(tmp_db):
    with pytest.raises(ValueError):
        store.add_post("")
    with pytest.raises(ValueError):
        store.add_post("   ")
    assert store.list_posts() == []


def test_update_post(tmp_db):
    pid = store.add_post("旧标题", "旧内容")
    store.update_post(pid, title="新标题")
    got = store.get_post(pid)
    assert got["title"] == "新标题"
    assert got["content"] == "旧内容"
    store.update_post(pid, content="新内容")
    got = store.get_post(pid)
    assert got["content"] == "新内容"
    assert got["updated_at"] >= got["created_at"]


def test_update_empty_title_raises(tmp_db):
    pid = store.add_post("标题")
    with pytest.raises(ValueError):
        store.update_post(pid, title="")
    assert store.get_post(pid)["title"] == "标题"


def test_delete_post(tmp_db):
    pid = store.add_post("待删")
    store.delete_post(pid)
    assert store.get_post(pid) is None
    assert store.list_posts() == []


def test_list_order_by_updated_at_desc(tmp_db):
    p1 = store.add_post("A")
    store.add_post("B")
    store.update_post(p1, content="x")  # p1 更新后最新
    posts = store.list_posts()
    assert posts[0]["id"] == p1


def test_long_title_boundary(tmp_db):
    long_title = "长" * 500
    pid = store.add_post(long_title)
    assert store.get_post(pid)["title"] == long_title


def test_registry_discovers_blog_module(tmp_path):
    from core.config import AppConfig
    from modules.registry import ModuleContext, ModuleRegistry

    ctx = ModuleContext(config=AppConfig(path=str(tmp_path / "settings.json")), host_window=None, app=None)
    reg = ModuleRegistry(ctx)
    mod = reg.get("blog")
    assert mod is not None
    assert mod.name == "Blog"
    assert reg.is_enabled("blog") is True