"""todo_store 类别数据层测试（Todo 2：迁移 + CRUD + 失败路径）。

覆盖：旧库 DISTINCT 类别迁移 + 幂等、add_category 去重、rename_category
传播到 todo_notes、delete_category 清空引用行、add_todo 新类别持久化、
get_categories 返回 list[str]、空名/重名/删除不存在等失败路径。
"""
import sqlite3

import pytest

from modules import todo_store as _ts


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_legacy_notes(categories):
    """模拟旧库：删掉 todo_categories 表，向 todo_notes 灌入给定类别。

    迁移在 _get_conn() 每次调用时执行（CREATE TABLE IF NOT EXISTS +
    INSERT OR IGNORE SELECT DISTINCT），因此先删表再灌数据即可复现
    「旧库首次调用触发迁移」的场景。
    """
    conn = sqlite3.connect(_ts.DB_PATH)
    conn.execute("DROP TABLE IF EXISTS todo_categories")
    conn.execute("DELETE FROM todo_notes")
    for i, cat in enumerate(categories):
        conn.execute(
            "INSERT INTO todo_notes (title, category, done, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (f"legacy_{i}", cat, f"2020-01-01 00:00:{i:02d}", f"2020-01-01 00:00:{i:02d}"),
        )
    conn.commit()
    conn.close()


def _todo_category(tid):
    """返回指定便签的 category（经公开 API get_todos）。"""
    return next(t for t in _ts.get_todos() if t["id"] == tid)["category"]


# ---------------------------------------------------------------------------
# 1. 迁移：旧库 DISTINCT 类别灌入新表 + 幂等
# ---------------------------------------------------------------------------

class TestMigration:
    def test_seeds_distinct_categories_from_legacy_notes(self):
        """旧库（无 todo_categories 表）首次 get_categories 触发迁移，3 个类别全在。"""
        _seed_legacy_notes(["工作", "生活", "学习"])
        assert set(_ts.get_categories()) == {"工作", "生活", "学习"}

    def test_migration_is_idempotent(self):
        """重复 get_categories / _get_conn 不重复插入，类别数不变。"""
        _seed_legacy_notes(["工作", "生活", "学习"])
        _ts.get_categories()
        _ts.get_categories()
        _ts._get_conn().close()
        assert set(_ts.get_categories()) == {"工作", "生活", "学习"}

    def test_migration_skips_empty_category(self):
        """迁移忽略空类别（category='' 不入表）。"""
        _seed_legacy_notes(["工作", ""])
        assert _ts.get_categories() == ["工作"]


# ---------------------------------------------------------------------------
# 2. get_categories 返回类型与排序
# ---------------------------------------------------------------------------

class TestGetCategories:
    def test_returns_list_of_str(self):
        """get_categories 返回 list[str]。"""
        cats = _ts.get_categories()
        assert isinstance(cats, list)
        assert all(isinstance(c, str) for c in cats)

    def test_sorted_by_name(self):
        """类别按名称升序返回。"""
        _ts.add_category("beta")
        _ts.add_category("alpha")
        assert _ts.get_categories() == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# 3. add_category
# ---------------------------------------------------------------------------

class TestAddCategory:
    def test_add_new_category_appears(self):
        """新增类别出现在 get_categories。"""
        cid = _ts.add_category("工作")
        assert isinstance(cid, int)
        assert "工作" in _ts.get_categories()

    def test_add_duplicate_raises_integrity_error(self):
        """重名新增抛 IntegrityError。"""
        _ts.add_category("工作")
        with pytest.raises(sqlite3.IntegrityError):
            _ts.add_category("工作")

    def test_add_empty_name_raises_value_error(self):
        """空名抛 ValueError。"""
        with pytest.raises(ValueError):
            _ts.add_category("")

    def test_add_whitespace_name_raises_value_error(self):
        """纯空白名抛 ValueError。"""
        with pytest.raises(ValueError):
            _ts.add_category("   ")

    def test_rejected_names_not_written(self):
        """被拒绝的空名/重名不写入库。"""
        _ts.add_category("工作")
        with pytest.raises(ValueError):
            _ts.add_category("")
        with pytest.raises(ValueError):
            _ts.add_category("   ")
        with pytest.raises(sqlite3.IntegrityError):
            _ts.add_category("工作")
        assert _ts.get_categories() == ["工作"]


# ---------------------------------------------------------------------------
# 4. rename_category 传播到 todo_notes
# ---------------------------------------------------------------------------

class TestRenameCategory:
    def test_rename_propagates_to_todo_notes(self):
        """重命名后 todo_notes 引用行同步更新。"""
        _ts.add_category("旧类")
        tid = _ts.add_todo("便签", category="旧类")
        _ts.rename_category("旧类", "新类")
        assert _ts.get_categories() == ["新类"]
        assert _todo_category(tid) == "新类"

    def test_rename_to_existing_name_raises_and_leaves_db_unchanged(self):
        """重名为已存在类别抛 IntegrityError 且库不变。"""
        _ts.add_category("A")
        _ts.add_category("B")
        tid = _ts.add_todo("便签", category="A")
        with pytest.raises(sqlite3.IntegrityError):
            _ts.rename_category("A", "B")
        assert sorted(_ts.get_categories()) == ["A", "B"]
        assert _todo_category(tid) == "A"

    def test_rename_to_empty_raises_value_error(self):
        """重命名为空名抛 ValueError。"""
        _ts.add_category("A")
        with pytest.raises(ValueError):
            _ts.rename_category("A", "")


# ---------------------------------------------------------------------------
# 5. delete_category 清空引用行
# ---------------------------------------------------------------------------

class TestDeleteCategory:
    def test_delete_blanks_referencing_rows_and_removes_category(self):
        """删除类别后引用行 category=='' 且类别消失。"""
        _ts.add_category("工作")
        tid = _ts.add_todo("便签", category="工作")
        _ts.delete_category("工作")
        assert "工作" not in _ts.get_categories()
        assert _todo_category(tid) == ""

    def test_delete_nonexistent_is_idempotent_noop(self):
        """删除不存在的类别是幂等空操作（不抛异常）。"""
        _ts.add_category("工作")
        _ts.delete_category("不存在")
        assert _ts.get_categories() == ["工作"]


# ---------------------------------------------------------------------------
# 6. add_todo 新类别持久化
# ---------------------------------------------------------------------------

class TestAddTodoCategoryPersistence:
    def test_add_todo_with_new_category_persists(self):
        """add_todo(category='新类') 后 get_categories 含它。"""
        _ts.add_todo("便签", category="新类")
        assert "新类" in _ts.get_categories()