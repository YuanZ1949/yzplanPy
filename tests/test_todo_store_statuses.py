"""todo_store 自定义状态数据层测试（TDD: 先写失败测试）。"""
import pytest
from modules.todo_store import (
    add_todo, update_todo,
    add_status, get_statuses, rename_status, set_status_color,
    delete_status, get_or_create_status, _migrate_statuses,
    _get_conn,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _status_rows():
    """返回 todo_statuses 全部行（id, name, color, sort_order, is_done_like）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, name, color, sort_order, is_done_like FROM todo_statuses ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# 1. 迁移幂等性
# ---------------------------------------------------------------------------

class TestMigrationIdempotent:
    def test_first_migration_seeds_two_builtins(self):
        """首次迁移插入「待办」和「已完成」两条内置状态。"""
        _migrate_statuses()
        rows = _status_rows()
        names = [r[1] for r in rows]
        assert "待办" in names
        assert "已完成" in names
        assert len(rows) == 2

    def test_second_migration_no_duplicate(self):
        """重复调用迁移不产生额外行。"""
        _migrate_statuses()
        _migrate_statuses()
        _migrate_statuses()
        rows = _status_rows()
        assert len(rows) == 2

    def test_builtin_done_like_flags(self):
        """「待办」is_done_like=0，「已完成」is_done_like=1。"""
        _migrate_statuses()
        rows = _status_rows()
        by_name = {r[1]: r for r in rows}
        assert by_name["待办"][4] == 0   # is_done_like
        assert by_name["已完成"][4] == 1

    def test_migration_preserves_custom_statuses(self):
        """迁移不会覆盖用户已自定义添加的状态。"""
        _migrate_statuses()
        add_status("进行中")
        # 再次迁移，自定义状态仍存在
        _migrate_statuses()
        rows = _status_rows()
        names = [r[1] for r in rows]
        assert "进行中" in names
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# 2. done=1 行迁移后 status_id 指向「已完成」
# ---------------------------------------------------------------------------

class TestMigrationDataBackfill:
    def test_done_1_migrates_to_completed_status(self):
        """done=1 的已有行迁移后 status_id 指向「已完成」，done 保持 1。"""
        tid = add_todo("old_done", content="x", priority=1)
        update_todo(tid, done=1)
        _migrate_statuses()
        conn = _get_conn()
        row = conn.execute(
            "SELECT status_id, done FROM todo_notes WHERE id = ?", (tid,)
        ).fetchone()
        conn.close()
        # status_id 指向已完成
        completed_id = next(r[0] for r in _status_rows() if r[1] == "已完成")
        assert row[0] == completed_id
        assert row[1] == 1

    def test_done_0_migrates_to_todo_status(self):
        """done=0 的已有行迁移后 status_id 指向「待办」，done 保持 0。"""
        tid = add_todo("old_pending", content="y", priority=0)
        _migrate_statuses()
        conn = _get_conn()
        row = conn.execute(
            "SELECT status_id, done FROM todo_notes WHERE id = ?", (tid,)
        ).fetchone()
        conn.close()
        todo_id = next(r[0] for r in _status_rows() if r[1] == "待办")
        assert row[0] == todo_id
        assert row[1] == 0

    def test_new_todo_gets_todo_status_after_migration(self):
        """迁移后新建的便签自动关联「待办」状态。"""
        _migrate_statuses()
        tid = add_todo("fresh")
        conn = _get_conn()
        row = conn.execute("SELECT status_id FROM todo_notes WHERE id = ?", (tid,)).fetchone()
        conn.close()
        todo_id = next(r[0] for r in _status_rows() if r[1] == "待办")
        assert row[0] == todo_id


# ---------------------------------------------------------------------------
# 3. get_statuses 排序
# ---------------------------------------------------------------------------

class TestGetStatuses:
    def test_sorted_by_sort_order(self):
        """get_statuses 按 sort_order ASC, id ASC 排序。"""
        _migrate_statuses()
        add_status("C状态", sort_order=3)
        add_status("A状态", sort_order=1)
        statuses = get_statuses()
        names = [s["name"] for s in statuses]
        # 待办(0) < A状态(1) < 已完成(0 but created first so sort 2nd) < C状态(3)
        # Actually: 待办(0) and 已完成(0) both sort_order=0, so by id: 待办 first
        # A状态(1) next, C状态(3) last
        assert names.index("待办") < names.index("A状态") < names.index("C状态")

    def test_returns_dicts_with_expected_keys(self):
        """返回的每条记录包含 id, name, color, sort_order, is_done_like。"""
        _migrate_statuses()
        statuses = get_statuses()
        for s in statuses:
            assert "id" in s
            assert "name" in s
            assert "color" in s
            assert "sort_order" in s
            assert "is_done_like" in s


# ---------------------------------------------------------------------------
# 4. add_status
# ---------------------------------------------------------------------------

class TestAddStatus:
    def test_add_status_returns_id(self):
        """add_status 返回新状态 ID。"""
        _migrate_statuses()
        sid = add_status("进行中")
        assert isinstance(sid, int)
        assert sid > 0

    def test_add_status_appears_in_list(self):
        """添加后 get_statuses 包含新状态。"""
        _migrate_statuses()
        add_status("已搁置")
        names = [s["name"] for s in get_statuses()]
        assert "已搁置" in names

    def test_add_status_with_color(self):
        """add_status 可指定 color。"""
        _migrate_statuses()
        sid = add_status("自定义", color="#ff0000")
        conn = _get_conn()
        row = conn.execute("SELECT color FROM todo_statuses WHERE id = ?", (sid,)).fetchone()
        conn.close()
        assert row[0] == "#ff0000"

    def test_add_status_duplicate_name_raises(self):
        """add_status 同名抛 IntegrityError。"""
        _migrate_statuses()
        with pytest.raises(Exception):
            add_status("待办")


# ---------------------------------------------------------------------------
# 5. rename_status
# ---------------------------------------------------------------------------

class TestRenameStatus:
    def test_rename_status(self):
        """rename_status 成功改名。"""
        _migrate_statuses()
        sid = add_status("旧名")
        rename_status(sid, "新名")
        names = [s["name"] for s in get_statuses()]
        assert "新名" in names
        assert "旧名" not in names

    def test_rename_status_duplicate_rejects(self):
        """rename_status 重名为已存在的名字抛异常。"""
        _migrate_statuses()
        # 「待办」已存在
        todo_id = next(s["id"] for s in get_statuses() if s["name"] == "待办")
        with pytest.raises(Exception):
            rename_status(todo_id, "已完成")


# ---------------------------------------------------------------------------
# 6. set_status_color
# ---------------------------------------------------------------------------

class TestSetStatusColor:
    def test_set_color(self):
        """set_status_color 更新颜色。"""
        _migrate_statuses()
        sid = add_status("测试色")
        set_status_color(sid, "#00ff00")
        conn = _get_conn()
        row = conn.execute("SELECT color FROM todo_statuses WHERE id = ?", (sid,)).fetchone()
        conn.close()
        assert row[0] == "#00ff00"


# ---------------------------------------------------------------------------
# 7. delete_status 回退引用行到「待办」
# ---------------------------------------------------------------------------

class TestDeleteStatus:
    def test_delete_status_fallback_to_todo(self):
        """删除一个状态后，引用它的 todos 被回退到「待办」。"""
        _migrate_statuses()
        sid = add_status("临时状态")
        # 新建便签并设为临时状态
        tid = add_todo("临时便签")
        update_todo(tid, status_id=sid)
        # 删除临时状态
        delete_status(sid)
        # 便签应回退到「待办」
        todo_status_id = next(s["id"] for s in get_statuses() if s["name"] == "待办")
        conn = _get_conn()
        row = conn.execute("SELECT status_id, done FROM todo_notes WHERE id = ?", (tid,)).fetchone()
        conn.close()
        assert row[0] == todo_status_id
        assert row[1] == 0  # 「待办」is_done_like=0 → done=0

    def test_delete_builtin_todo_raises(self):
        """不能删除内置的「待办」状态。"""
        _migrate_statuses()
        todo_id = next(s["id"] for s in get_statuses() if s["name"] == "待办")
        with pytest.raises(Exception):
            delete_status(todo_id)

    def test_delete_builtin_completed_fallback(self):
        """删除「已完成」后，引用它的 todos 回退到「待办」。"""
        _migrate_statuses()
        completed_id = next(s["id"] for s in get_statuses() if s["name"] == "已完成")
        todo_status_id = next(s["id"] for s in get_statuses() if s["name"] == "待办")
        # 新建一条标记为已完成的便签
        tid = add_todo("done_item")
        update_todo(tid, done=1)
        # 删除「已完成」状态
        delete_status(completed_id)
        conn = _get_conn()
        row = conn.execute("SELECT status_id, done FROM todo_notes WHERE id = ?", (tid,)).fetchone()
        conn.close()
        assert row[0] == todo_status_id
        assert row[1] == 0


# ---------------------------------------------------------------------------
# 8. get_or_create_status
# ---------------------------------------------------------------------------

class TestGetOrCreateStatus:
    def test_creates_new_status(self):
        """get_or_create_status 新名字创建新状态。"""
        _migrate_statuses()
        sid = get_or_create_status("全新状态")
        assert isinstance(sid, int)
        names = [s["name"] for s in get_statuses()]
        assert "全新状态" in names

    def test_returns_same_id_on_second_call(self):
        """get_or_create_status 第二次调用返回同一 ID。"""
        _migrate_statuses()
        sid1 = get_or_create_status("幂等测试")
        sid2 = get_or_create_status("幂等测试")
        assert sid1 == sid2

    def test_existing_builtin_returns_builtin_id(self):
        """get_or_create_status 查找已有的内置状态返回其 ID。"""
        _migrate_statuses()
        todo_id = next(s["id"] for s in get_statuses() if s["name"] == "待办")
        assert get_or_create_status("待办") == todo_id


# ---------------------------------------------------------------------------
# 9. update_todo status_id 与 done 同步
# ---------------------------------------------------------------------------

class TestUpdateTodoStatusIdSync:
    def test_status_id_sets_done_1_when_is_done_like(self):
        """status_id 指向 is_done_like=1 的状态 → done=1。"""
        _migrate_statuses()
        completed_id = next(s["id"] for s in get_statuses() if s["name"] == "已完成")
        tid = add_todo("sync_test")
        update_todo(tid, status_id=completed_id)
        conn = _get_conn()
        row = conn.execute("SELECT done FROM todo_notes WHERE id = ?", (tid,)).fetchone()
        conn.close()
        assert row[0] == 1

    def test_status_id_sets_done_0_when_not_done_like(self):
        """status_id 指向 is_done_like=0 的状态 → done=0。"""
        _migrate_statuses()
        todo_id = next(s["id"] for s in get_statuses() if s["name"] == "待办")
        tid = add_todo("sync_test_2")
        update_todo(tid, done=1)
        update_todo(tid, status_id=todo_id)
        conn = _get_conn()
        row = conn.execute("SELECT done FROM todo_notes WHERE id = ?", (tid,)).fetchone()
        conn.close()
        assert row[0] == 0

    def test_custom_status_not_done_like(self):
        """自定义状态（is_done_like=0）设为 status_id → done=0。"""
        _migrate_statuses()
        sid = add_status("进行中")
        tid = add_todo("custom_sync")
        update_todo(tid, done=1)
        update_todo(tid, status_id=sid)
        conn = _get_conn()
        row = conn.execute("SELECT done FROM todo_notes WHERE id = ?", (tid,)).fetchone()
        conn.close()
        assert row[0] == 0

    def test_explicit_done_overrides_status_sync(self):
        """同时传 status_id 和 done 时，done 被 status_id 覆盖。"""
        _migrate_statuses()
        completed_id = next(s["id"] for s in get_statuses() if s["name"] == "已完成")
        tid = add_todo("override_test")
        # done=0 但 status_id=已完成 → done 应为 1
        update_todo(tid, done=0, status_id=completed_id)
        conn = _get_conn()
        row = conn.execute("SELECT done FROM todo_notes WHERE id = ?", (tid,)).fetchone()
        conn.close()
        assert row[0] == 1

    def test_update_todo_backward_compat_no_status_id(self):
        """不传 status_id 的旧式 update_todo(done=1) 仍然正常工作。"""
        _migrate_statuses()
        tid = add_todo("compat_test")
        update_todo(tid, done=1)
        conn = _get_conn()
        row = conn.execute("SELECT done FROM todo_notes WHERE id = ?", (tid,)).fetchone()
        conn.close()
        assert row[0] == 1
