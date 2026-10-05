"""right_menu 提权作业的**原语与执行**：作业 ops 的形状定义 + 写后回读校验。

从 `elevate.py` 拆出（250 物理行上限）。拆分边界：只负责「一条 op → 一个结果条目」，
完全不知道作业文件、子进程、UAC 是什么；`elevate.py` 反向依赖本模块（提权侧把
backend 注入进来），因此本模块**不得**反向 import `elevate`——否则两条 import 路径
互为前提。

Qt-free：与 `elevate.py` 同一条约束（`--elevated-job` 早退通道会 import 本文件），
只用 stdlib，不 import PySide6 / qfluentwidgets / module.py。

一条不变量：**写后回读校验**。`RegistryBackend` 是 never-raise 契约，HKLM 未提权的
写入会静默无声——返回值上「无权限」与「成功」无法区分，只有回读能。所以每个写/删
之后都回读确认真的落地，不落地即 `write_failed`；否则「全部成功」是假的，上层账本
会记录没发生过的改动。
"""

__all__ = ["set_op", "delete_op", "delete_tree_op", "exec_ops"]


# ── 作业原语（ops 的形状定义；GUI 侧与提权侧共用同一套构造器）────────────
def set_op(hive, path, name, value):
    """写一个值（`name` 为 ""/None 即默认值）。"""
    return {"action": "set", "hive": str(hive or ""), "path": str(path or ""),
            "name": "" if name is None else str(name),
            "value": "" if value is None else str(value)}


def delete_op(hive, path, name=None):
    """删一个值（`name` 为 None 即默认值；值本来就不存在也算成功）。"""
    return {"action": "delete", "hive": str(hive or ""), "path": str(path or ""),
            "name": None if name is None else str(name)}


def delete_tree_op(hive, path):
    """删一个键及其全部子键（键级删除，不是值级）。"""
    return {"action": "delete_tree", "hive": str(hive or ""), "path": str(path or "")}


# ── 执行 + 写后回读校验 ────────────────────────────────────────────────
def _text(value):
    """值/值名文本化：None → ""（即注册表的默认值）。"""
    return "" if value is None else str(value)


def _entry(ok, op, name, error=None, detail=None):
    """结果条目：回显 op 上下文（action/hive/path/name），失败时带 error + 排查细节。"""
    item = {"ok": bool(ok), "action": op.get("action"), "hive": op.get("hive"),
            "path": op.get("path"), "name": name}
    if not ok:
        item["error"] = error or "op_failed"
        if detail:
            item["detail"] = detail
    return item


def _exec_one(backend, op):
    """执行单条原语并回读校验；任何异常降级为 op_failed（绝不向上抛）。

    校验口径（T2 评审裁定）：`set` 后回读值非 None、`delete` 后回读值为 None、
    `delete_tree` 后该键无子键。三者任一不满足即 write_failed——因为后端的
    never-raise 契约让「无权限」与「成功」在返回值上无法区分，只有回读能。
    """
    if not isinstance(op, dict):
        return {"ok": False, "error": "bad_op"}
    action = str(op.get("action") or "")
    hive, path = op.get("hive"), op.get("path")
    try:
        if action == "set":
            name, value = _text(op.get("name")), _text(op.get("value"))
            backend.set(hive, path, name, value)
            ok = backend.get(hive, path, name) is not None
            return _entry(ok, op, name, "write_failed", f"回读为空：{hive}\\{path}")
        if action == "delete":
            name = op.get("name")           # None 即默认值，语义与后端一致
            backend.delete(hive, path, name)
            ok = backend.get(hive, path, name) is None
            return _entry(ok, op, name, "write_failed", f"回读仍有值：{hive}\\{path}")
        if action == "delete_tree":
            backend.delete_tree(hive, path)
            ok = backend.list_keys(hive, path) == []
            return _entry(ok, op, None, "write_failed", f"回读仍有子键：{hive}\\{path}")
        return _entry(False, op, op.get("name"), f"unknown_action: {action}")
    except Exception:                       # 契约外的后端也不拖垮整批作业
        return _entry(False, op, op.get("name"), "op_failed")


def exec_ops(backend, ops):
    """按顺序执行一批原语 → 结果条目列表（与 ops 逐条一一对应，不吞条数）。"""
    return [_exec_one(backend, op) for op in (ops or [])]
