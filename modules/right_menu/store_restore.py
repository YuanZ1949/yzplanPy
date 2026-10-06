"""right_menu 一键还原：把账本记下的每一类改动逐条撤销，汇总成一份 report。

本文件**顶层零 import**（连 stdlib 都没有）：`store.py` 在文件末尾
`from .store_restore import restore_all` 再导出，实现因此可以独立成文件而不与 store 构成循环
依赖——`import store` 与 `import store_restore` 两种顺序都成立。其余操作层（`ops` /
`shellnew` / `custom` / `yzmenu` / `classic`）**只在函数体内 import**：它们各自都 import store，
顶层 import 会让两者在包初始化期互相找对方的属性（循环依赖），放到调用时才互相看见。

跨任务契约：
  * **Qt-free**：只 import 本包的纯 Python 操作层（它们都不 import Qt）。
  * **永不抛**：每条子操作单独 try/except，单条失败记 `ok=False` 也不中断整批——还原是
    「尽量把系统拖回原点」的动作，一条坏账不该让剩下的改动全都留在原地。
  * **账本按条清理，不整体清空**（控制器裁决，偏离 plan 字面的「清空数组」）：成功条目已由各子
    操作逐条销账（`apply_op` / `restore_shellnew` / `delete_item` / `uninstall_yzmenu` 都是写
    成功才摘账）；**失败条目保留在账本**——注册表仍处于已改状态，账本必须如实记录供重试
    （与 T6/T9 的「失败不碰账本」同一条纪律）；「键已不存在」的空条目由本层手动摘除
    （没什么可还原的，留着只会每次都报错）。
  * **只撤销 YZplan 记录的**：用户自己装的东西一律不碰。经典菜单也只在明确读到 `enabled`
    时才关回去——`unknown` 意味着这个 CLSID 被别的软件注册着，动它会破坏对方。
  * **撤销顺序**：disabled → shellnew_hidden → custom_items → yzmenu → classic，从最局部到最
    全局，后一步不会推翻前一步已经做完的事。
"""

__all__ = ["restore_all"]


# ── report 行与账本条目的取值 ───────────────────────────────────────────
def _row(kind, ok, detail):
    """report 的一行，**键固定为三个**（UI 与还原点只认 kind/ok/detail）。"""
    return {"kind": kind, "ok": bool(ok), "detail": str(detail)}


def _field(item, key, default=None):
    """账本条目取值；非字典 / 缺字段一律取缺省值（账本只保证是列表，不保证每条是字典）。"""
    return item.get(key, default) if isinstance(item, dict) else default


def _norm(hive, path):
    """(hive, 路径) → 账本与扫描结果的同一把尺子（注册表键名与 hive 都大小写不敏感）。"""
    return (str(hive or "").strip().casefold(),
            str(path or "").strip().strip("\\").casefold())


def _attempt(report, kind, target, call):
    """跑一次子操作 → append 一行 report；异常降级成 `ok=False`（单条失败不中断整批还原）。"""
    try:
        out = call()                       # 子操作按契约返回 {"ok","detail"}
        ok, detail = bool(out.get("ok")), str(out.get("detail") or "")
    except Exception:                      # 契约外的返回值/后端也不拖垮整批还原
        ok, detail = False, "还原失败（内部错误）"
    report.append(_row(kind, ok, f"{target}：{detail}" if target else detail))
    return report[-1]


def _installed_yzmenu(yzmenu_mod, backend, from_ledger):
    """「YZplan 子菜单装没装」：`from_ledger or 注册表实况`；后端抛异常时只信账本。"""
    try:
        return bool(from_ledger) or bool(yzmenu_mod.get_yzmenu_state(backend).get("installed"))
    except Exception:
        return bool(from_ledger)


# ── 一键还原 ────────────────────────────────────────────────────────────
def restore_all(backend, *, store_mod=None):
    """把账本里的每一类改动逐条撤销 → `{"ok": bool, "report": [{"kind","ok","detail"}, ...]}`。

    `store_mod` 用于注入账本模块（默认本包的 `store`），并原样透传给各子操作
    （它们自己也在记账本）。`ok` 是全部 report 行的合取：任一条失败即 False，调用方据此提示
    「部分未还原」并保留账本条目供重试。账本里没有的类别直接跳过，不入 report（空账本调用
    返回 `{"ok": True, "report": []}`——没东西可还原不是错误）。
    """
    from . import classic, custom, ops, shellnew, store as _store, yzmenu

    ledger = store_mod or _store
    state = ledger.load()                  # 一次读全量：下面每个子操作都会重写账本
    report = []
    ledger.backup_snapshot("restore_all")  # 动任何注册表之前先留快照（与 ops 同一条时序）

    # 1) 隐藏项：apply_op 自带回读 / 原值回填 / 成功才销账，HKLM 自动走提权作业
    for entry in list(state["disabled"]):
        op = {"action": "restore", "hive": _field(entry, "hive"),
              "key_path": _field(entry, "key_path"),
              "name": _field(entry, "name") or None,      # 账本用 "" 表示默认值
              "original": _field(entry, "original")}
        _attempt(report, "disabled", _field(entry, "key_path"),
                 lambda: ops.apply_op(backend, op, store_mod=store_mod))

    # 2) ShellNew 隐藏：账本只有 (hive, 路径, 原值名)，得去扫描结果里找同一把键才能还原
    scan = shellnew.scan_shellnew(backend)
    for entry in list(state["shellnew_hidden"]):
        hive, path = _field(entry, "hive"), _field(entry, "path")
        item = next((i for i in scan
                     if _norm(i.get("hive"), i.get("key_path")) == _norm(hive, path)), None)
        if item is None:                   # 扩展名/键已被用户或别的软件删掉
            ledger.remove_shellnew_hidden(hive, path, _field(entry, "orig_name"))
            report.append(_row("shellnew", True, f"{path}：键已不存在，跳过"))
            continue
        _attempt(report, "shellnew", path,
                 lambda: shellnew.restore_shellnew(backend, item, store_mod=store_mod))

    # 3) 自定义项：删掉它的全部注册表投影；写失败时 delete_item 自己保留账本条目
    for entry in list(state["custom_items"]):
        item_id = str(_field(entry, "id") or "").strip()
        label = _field(entry, "title") or item_id or "(无 id)"
        _attempt(report, "custom", label,
                 lambda: custom.delete_item(backend, item_id, store_mod=store_mod))

    # 4) YZplan 子菜单：账本与注册表任一为「已安装」都要卸（账本只在写落地后才写，
    #    反过来注册表已装而账本为空的情形同样必须卸，否则菜单会留在系统里）
    if _installed_yzmenu(yzmenu, backend, state["yzmenu"]["installed"]):
        _attempt(report, "yzmenu", "YZplan 子菜单",
                 lambda: yzmenu.uninstall_yzmenu(backend, store_mod=store_mod))

    # 5) 经典菜单总开关：只在明确读到 enabled 时关回去（unknown 不碰，见模块 docstring）
    try:
        classic_state = classic.get_classic_state(backend)
    except Exception:
        classic_state = "unknown"
    if classic_state == "enabled":
        _attempt(report, "classic", "经典右键菜单", lambda: classic.disable_classic(backend))

    ledger.add_restore_point("restore_all", report)
    return {"ok": all(row["ok"] for row in report), "report": report}
