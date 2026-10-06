"""right_menu.widgets.page_tabs.shellnew_rows：「新建」菜单表的纯逻辑层（Qt-free）。

刻意**不 import 任何 Qt**（连 `import_qt` 都没有）：这里只有常量 + 纯函数（吃 dict、出
str / 按钮列表），所以既能被 `shellnew_tab.py` 的控件渲染调用，也能被测试直接 import
断言——不需要 QApplication。

单独成文件的首要理由是 `shellnew_tab.py` 的 250 物理行硬上限：表头列下标、kind→胶囊映射、
「本行该铺哪些按钮」这三块是与控件无关的决策，留在 UI 文件里只会挤掉注释。

**`WRITE_FNS` 只存函数名、不存函数对象**：`shellnew` 的纪律是「调用时取模块属性」（直接
绑定 `run_job` 会在 import 时把名字钉死，monkeypatch 拦不到 UAC 被取消这类分支），故
`_write` 在工作线程内才 `getattr`。
"""

#: 结果表头列序
HEADERS = ("扩展名", "类型", "模板", "状态", "操作")
#: 表格列下标（与 HEADERS 一一对应）
COL_KIND, COL_STATE, COL_ACTION = 1, 3, 4

#: `scan_shellnew` 的 kind → (类型列文字, 胶囊色)。未知 kind 显示「未知/error」，
#: 不伪装成正常类型——扫描认不出的值名组合（第三方自造的值）就该让人看见。
KIND_CHIPS = {"null": ("空文件", "info"), "template": ("模板", "success"),
              "data": ("数据", "info"), "command": ("命令", "warning"),
              "unknown": ("未知", "error")}
#: 新增对话框的类型下拉：显示文字 → `create_shellnew` 的 kind
ADD_KINDS = (("空文件", "null"), ("模板文件", "template"))
#: 写动作名 → `shellnew` 模块内的函数名（**调用时才 getattr**，monkeypatch 才拦得到）
WRITE_FNS = {"hide": "hide_shellnew", "restore": "restore_shellnew",
             "delete": "delete_shellnew"}

#: 未扫描时的默认提示
HINT_IDLE = "点「刷新」扫描「新建」菜单项；扫描会枚举两个 hive 的 Software\\Classes，请稍候。"
#: 0 结果提示（含未提权读不到 HKLM 的排查口径）
EMPTY_HINT = ("两个 hive 下都没扫到 ShellNew 项。若资源管理器里明明有，请确认本进程能读 "
              "HKLM（未提权时 HKLM 项读不到）。")


def write(action, backend, row):
    """按动作名取 `shellnew` 的函数并调用 —— **必须在工作线程内调**（注册表读写不进 UI 线程）。"""
    from ... import shellnew
    return getattr(shellnew, WRITE_FNS[action])(backend, row)


def kind_chip(row):
    """类型列的 (文字, 胶囊色)；缺 `kind` 的畸形行按 unknown 处理。"""
    row = row if isinstance(row, dict) else {}
    return KIND_CHIPS.get(str(row.get("kind") or ""), KIND_CHIPS["unknown"])


def state_chip(row):
    """状态列的 (文字, 胶囊色)：已隐藏 → 警告色，仍显示 → 成功色。"""
    row = row if isinstance(row, dict) else {}
    return ("已隐藏", "warning") if row.get("hidden") else ("显示", "success")


def actions_for(row):
    """本行该铺哪些操作按钮 `[(文字, (动作, 行))]`。

    已隐藏 → 只给「恢复」（再点隐藏是空转）；未隐藏 → 「隐藏」，且只有 HKCU 项加
    「删除」（`delete_shellnew` 对 HKLM 直接拒绝——系统项仅支持隐藏）。
    行字段一律 `.get()` 兜底：扫描结果来自注册表，畸形行不能让渲染崩在 UI 线程上。
    """
    row = row if isinstance(row, dict) else {}
    if row.get("hidden"):
        return [("恢复", ("restore", row))]
    buttons = [("隐藏", ("hide", row))]
    if str(row.get("hive") or "").strip().lower() == "hkcu":
        buttons.append(("删除", ("delete", row)))
    return buttons


def add_kind(index):
    """对话框下拉下标 → `create_shellnew` 的 kind（越界回退到第一项）。"""
    return ADD_KINDS[index][1] if 0 <= index < len(ADD_KINDS) else ADD_KINDS[0][1]


def hint_for(count):
    """扫描完成后的提示文案（0 结果走含排查口径的 `EMPTY_HINT`）。"""
    if not count:
        return EMPTY_HINT
    return f"共 {count} 项；行尾可隐藏/恢复，HKCU 项还可删除。"