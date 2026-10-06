"""MCP 工具切片：Windows 右键菜单管理（right_menu_*）。

12 个工具覆盖扫描 / 隐藏还原 / 经典菜单 / 自定义项 CRUD / ShellNew / 一键还原 / 打开模块页（GUI
IPC）。与 GUI 侧共用同一套操作层，本切片只做参数归一、HKLM 守卫、结果收敛三件事。

跨切片契约：
  * **顶层零 Qt、零注册表写**：顶层只有 stdlib + `core.constants.DATA_DIR`（mcp_inbox 路径）；
    操作层与 `Win32Backend` 全部在**函数体内** import——导入期不碰注册表，monkeypatch 也拦得到。
  * **HKLM 一律拒绝**：MCP 进程无提权能力，操作层对 HKLM 的写会走 `elevate.run_job` 弹 UAC。
    故 hive == hklm 的写请求都在**任何操作层调用之前**返回 GUI 提示——`restore_all` 同理
    （账本含 HKLM 条目时，其提交路径同样要提权）。
  * **`_backend()` 是唯一注入口**：返回 `Win32Backend()`，测试整体替换为 `FakeRegistry` 即得
    零真实注册表读写；调用一律取模块属性（`ops.apply_op(...)`），不写 `from ... import
    apply_op`——直接绑定会在 import 时把名字钉死，monkeypatch 拦不到。
  * **GUI 双写**（spec §10）：不另开写 store 的口子——账本写入全在操作层内部，各写入口自带
    「备份 → 写 → 回读 → 记账本」时序。
"""
import json
import os
import time
import uuid

from core.constants import DATA_DIR

__all__ = ["TOOLS"]

_SCOPES = ("file", "directory", "background", "drive")
_HKLM_ERROR = "HKLM 操作需通过 GUI（提权流程），请在 YZplan 窗口中执行"
_NOT_FOUND = "未找到该扩展名的新建菜单项"


# ── 结果收敛与守卫 ─────────────────────────────────────────────────────
def _hklm_refused():
    """HKLM 写请求的固定拒绝；每次新建 dict（共享可变对象会被调用方改串味）。"""
    return {"ok": False, "error": _HKLM_ERROR}


def _is_hklm(value):
    """hive 是否为 HKLM（大小写/空白不敏感，与注册表后端同一把尺子）。"""
    return str(value or "").strip().casefold() == "hklm"


def _merged(out):
    """操作层 `{"ok","detail"}` → 统一形状：失败补 `error` 键；附加键（warnings/report）带出。"""
    out = out if isinstance(out, dict) else {"detail": "操作层返回非法"}
    row = {"ok": bool(out.get("ok")), "detail": str(out.get("detail") or "")}
    if not row["ok"]:
        row["error"] = row["detail"]
    return {**row, **{k: v for k, v in out.items() if k not in row}}


def _backend():
    """真实注册表后端；本切片唯一的注入口（测试整体替换为 FakeRegistry）。"""
    from modules.right_menu.registry_backend import Win32Backend
    return Win32Backend()


def _shellnew_scan(backend):
    """扫 ShellNew 项；后端异常降级成空列表（只读扫描不该让整次工具调用失败）。"""
    from modules.right_menu import shellnew

    try:
        return shellnew.scan_shellnew(backend)
    except Exception:
        return []


def right_menu_scan(args):
    """扫一个作用域的右键项；`scope == "all"` 时四作用域合并并附 ShellNew 列表（只读）。"""
    from modules.right_menu import scan

    scope = str(args.get("scope") or "file").strip().lower()
    backend = _backend()
    out = {"ok": True, "scope": scope,
           "items": [i for s in (_SCOPES if scope == "all" else (scope,))
                     for i in scan.scan_scope(backend, s)]}
    if scope == "all":
        out["shellnew"] = _shellnew_scan(backend)
    return out


def right_menu_set_disabled(args):
    """隐藏/恢复/删除某个右键项（hive + key_path）；HKLM 直接拒绝并指向 GUI。"""
    from modules.right_menu import ops

    op = {"action": str(args.get("action") or "disable").strip().lower(),
          "hive": str(args.get("hive") or "hkcu").strip().lower(),
          "key_path": str(args.get("key_path") or "").strip(),
          "name": args.get("name"), "original": args.get("original"), "builtin": bool(args.get("builtin"))}
    if _is_hklm(op["hive"]):
        return _hklm_refused()             # 守卫先于一切操作层调用（零 UAC 风险）
    return _merged(ops.apply_op(_backend(), op))


def right_menu_restore_all(args):
    """一键还原账本记下的全部改动；账本含 HKLM 条目时拒绝（其提交路径要提权）。"""
    from modules.right_menu import store

    try:
        ledger = store.load()
        entries = ledger.get("disabled") if isinstance(ledger, dict) else []
    except Exception:                       # 读不出账本：按空账本走，让 restore_all 自己报 ledger 行
        entries = []
    if any(_is_hklm(i.get("hive")) for i in entries if isinstance(i, dict)):
        return _hklm_refused()
    return _merged(store.restore_all(_backend()))


# ── 经典菜单 / YZplan 子菜单（都是 HKCU，直写不需提权）──────────────────
def right_menu_classic_state(args):
    """经典右键菜单三态（enabled/disabled/unknown）+ YZplan 子菜单安装状态（只读）。"""
    from modules.right_menu import classic, yzmenu

    try:
        backend = _backend()
        return {"ok": True, "classic": classic.get_classic_state(backend),
                "yzmenu": yzmenu.get_yzmenu_state(backend)}
    except Exception:                       # 读不到即「状态未知」，不把异常冒给 MCP 客户端
        return {"ok": True, "classic": "unknown", "yzmenu": {"installed": False, "actions": []}}


def right_menu_classic_set(args):
    """开关经典右键菜单（HKCU 直写）；`enable` 为真即切到经典菜单。"""
    from modules.right_menu import classic

    fn = classic.enable_classic if bool(args.get("enable")) else classic.disable_classic
    return _merged(fn(_backend()))


# ── 自定义项 CRUD ──────────────────────────────────────────────────────
def right_menu_custom_list(args):
    """自定义菜单项列表（账本的读视图）。"""
    from modules.right_menu import store

    return {"ok": True, "items": store.get_custom_items()}


def right_menu_custom_save(args):
    """新增/更新一个自定义项（校验 → 备份 → 账本 → 注册表投影 → 回读）；HKLM 拒绝。"""
    from modules.right_menu import custom

    item = args.get("item")
    if isinstance(item, dict) and _is_hklm(item.get("hive")):
        return _hklm_refused()
    return _merged(custom.save_item(_backend(), item))


def right_menu_custom_delete(args):
    """删除一个自定义项及其全部注册表投影；账本条目在 HKLM 时拒绝（删除要提权）。"""
    from modules.right_menu import custom, store

    item_id = str(args.get("item_id") or "").strip()
    item = next((i for i in store.get_custom_items() if isinstance(i, dict)
                 and str(i.get("id") or "").strip() == item_id), None)
    if item is not None and _is_hklm(item.get("hive")):
        return _hklm_refused()
    return _merged(custom.delete_item(_backend(), item_id))


# ── ShellNew（新建菜单）─────────────────────────────────────────────────
def right_menu_shellnew_scan(args):
    """扫两个 hive 下带 ShellNew 子键的扩展名（只读）。"""
    return {"ok": True, "items": _shellnew_scan(_backend())}


def _shellnew_apply(args, hide):
    """hide/restore 共用：按 (hive, ext) 定位项 → HKLM 守卫 → 调操作层；定位不到统一报「未找到…」。"""
    from modules.right_menu import shellnew

    backend, hive = _backend(), str(args.get("hive") or "hkcu").strip().lower()
    ext = str(args.get("ext") or "").strip().casefold()
    item = next((i for i in _shellnew_scan(backend) if str(i.get("hive") or "").strip().lower() == hive
                 and str(i.get("ext") or "").strip().casefold() == ext), None)
    if item is None:
        return {"ok": False, "error": _NOT_FOUND}
    if _is_hklm(item.get("hive")):
        return _hklm_refused()
    fn = shellnew.hide_shellnew if hide else shellnew.restore_shellnew
    return _merged(fn(backend, item))


def right_menu_shellnew_hide(args):
    """隐藏某扩展名的新建菜单项（值名加后缀，可原样还原）；HKLM 拒绝。"""
    return _shellnew_apply(args, True)


def right_menu_shellnew_restore(args):
    """恢复某扩展名的新建菜单项；HKLM 拒绝。"""
    return _shellnew_apply(args, False)


# ── GUI IPC ────────────────────────────────────────────────────────────
def _queue_menu_action(action):
    """往 `DATA_DIR/mcp_inbox` 写一条 `menu_action` 命令；函数内读模块全局 DATA_DIR（测试隔离入口）。"""
    inbox = os.path.join(DATA_DIR, "mcp_inbox")
    os.makedirs(inbox, exist_ok=True)
    payload = {"id": uuid.uuid4().hex, "command": "menu_action", "action": str(action),
               "time": time.strftime("%Y-%m-%d %H:%M:%S"), "silent": True}
    path = os.path.join(inbox, f"{payload['id']}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return {"ok": True, "queued": True, "command": "menu_action", "action": str(action), "inbox_file": path}


def right_menu_open_manager(args):
    """让正在运行的 GUI 打开 right_menu 模块页（本进程无权拉起 Qt 窗口，走 mcp_inbox）。"""
    return _queue_menu_action("open_manager")


# ── MCP 工具定义 ───────────────────────────────────────────────────────
def _tool(name, description, handler, props=None, required=None):
    """工具条目：handler 统一吃一个 args dict；`required` 非空才写进 schema。"""
    schema = {"type": "object", "properties": props or {}}
    if required:
        schema["required"] = list(required)
    return {"name": name, "description": description, "inputSchema": schema, "handler": lambda a: handler(a)}


_SCOPE = {"type": "string", "enum": [*_SCOPES, "all"],
          "description": "作用域，默认 file；all = 四作用域合并 + ShellNew"}
_HIVE = {"type": "string", "enum": ["hkcu", "hklm"], "description": "注册表根；HKLM 写会被拒绝"}
_EXT = {"type": "string", "description": "扩展名（含点），如 .txt"}

TOOLS = [
    _tool("right_menu_scan", "扫描 Windows 右键菜单项（只读）；scope=all 时含 ShellNew 列表。", right_menu_scan, {"scope": _SCOPE}),
    _tool("right_menu_set_disabled", "隐藏/恢复/删除某个右键菜单项（HKCU 直写）；HKLM 需在 GUI 中执行。",
          right_menu_set_disabled, {
              "action": {"type": "string", "enum": ["disable", "restore", "delete"], "description": "动作"},
              "hive": _HIVE, "key_path": {"type": "string", "description": "相对 hive 的完整键路径"},
              "name": {"type": "string", "description": "隐藏标记值名，缺省 LegacyDisable"},
              "original": {"type": "string", "description": "隐藏前的原值（还原时回填）"},
              "builtin": {"type": "boolean", "description": "系统内建伪项（delete 拒绝）"}},
          ["action", "hive", "key_path"]),
    _tool("right_menu_classic_state", "查询经典右键菜单状态（enabled/disabled/unknown）与 YZplan 子菜单状态。", right_menu_classic_state),
    _tool("right_menu_classic_set", "开关经典右键菜单（HKCU 直写，需重启资源管理器生效）。",
          right_menu_classic_set, {"enable": {"type": "boolean", "description": "true=经典菜单"}}),
    _tool("right_menu_custom_list", "列出全部自定义右键菜单项（账本读视图）。", right_menu_custom_list),
    _tool("right_menu_custom_save", "新增/更新自定义菜单项（校验 → 账本 → 注册表投影）；HKLM 拒绝。",
          right_menu_custom_save, {"item": {"type": "object", "description": "自定义项 DOM"}}, ["item"]),
    _tool("right_menu_custom_delete", "删除一个自定义菜单项及其注册表投影。",
          right_menu_custom_delete, {"item_id": {"type": "string", "description": "自定义项 id"}}, ["item_id"]),
    _tool("right_menu_shellnew_scan", "扫描「新建」菜单（ShellNew）的全部扩展名（只读）。", right_menu_shellnew_scan),
    _tool("right_menu_shellnew_hide", "隐藏某扩展名的新建菜单项（可原样还原）；HKLM 拒绝。",
          right_menu_shellnew_hide, {"hive": _HIVE, "ext": _EXT}, ["hive", "ext"]),
    _tool("right_menu_shellnew_restore", "恢复某扩展名的新建菜单项；HKLM 拒绝。",
          right_menu_shellnew_restore, {"hive": _HIVE, "ext": _EXT}, ["hive", "ext"]),
    _tool("right_menu_restore_all", "一键还原账本记录的全部改动（逐条撤销 + report）；含 HKLM 请用 GUI。", right_menu_restore_all),
    _tool("right_menu_open_manager", "让 YZplan 打开右键菜单管理器页面（经 mcp_inbox 投递）。", right_menu_open_manager),
]
