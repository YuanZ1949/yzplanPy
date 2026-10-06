"""right_menu.widgets.page_tabs.scan_rows：扫描表的纯逻辑层（表头、格式化、写操作 op）。

刻意 **Qt-free**：这里只有常量 + 纯函数（吃 dict、出 str/dict），所以既能被
`scan_tab.py` 的控件渲染调用，也能被测试直接 import 断言——不需要 QApplication。

**`_restore_marker` 是本文件存在的首要理由（T6-M7）**：scan 行只有一个 `disabled` 布尔
（`LegacyDisable` 与 `ProgrammaticAccessOnly` 任一存在即为真），恢复时若一律按
`name=None`（≡ `LegacyDisable`）去删，对「系统项本来用 `ProgrammaticAccessOnly` 隐藏」
的情况就会删错值名——标记还在，ops 却因回读 `LegacyDisable` 为 None 报「成功」。
隐藏动作则固定写 `LegacyDisable`，往返才自洽。
"""

#: 结果表头列序
HEADERS = ("名称", "作用域", "命令", "来源", "状态", "操作")
#: scope 键 → 中文标题（既作下拉框项，也作作用域列的显示文本）
SCOPE_LABELS = {"file": "文件", "directory": "文件夹",
                "background": "文件夹背景", "drive": "驱动器"}
#: 命令列最多显示多少字符（超出的进 tooltip）
CMD_MAX = 60
#: 未扫描时的默认提示
HINT_IDLE = "选择作用域后点「刷新」扫描；扫描会枚举整棵 HKCR，请稍候。"
#: 0 结果提示（含未提权读不到 HKLM 的排查口径）
EMPTY_HINT = ("这一作用域下没有扫到右键项。若资源管理器里明明有，请确认本进程能读 "
              "HKLM（未提权时 HKLM 项读不到）。")
#: 表格列下标（与 HEADERS 一一对应）
COL_COMMAND, COL_STATE, COL_ACTION = 2, 4, 5


def restore_marker(backend, row):
    """恢复动作该删哪个标记值名 → `"ProgrammaticAccessOnly"` 或 `None`（≡ LegacyDisable）。

    `ProgrammaticAccessOnly` 存在 → 必须删它；否则返回 `None` 让 ops 层按
    `LegacyDisable` 处理（与账本条目身份一致：`store._identity` 把 `None` 归一成 `""`）。
    行字段一律 `.get()` 兜底（扫描结果来自注册表，可能是畸形行）。

    **必须在工作线程里调**（注册表读不进 UI 线程）：调用方是 `op_for` 的 worker 闭包。
    """
    if backend.get(row.get("hive"), row.get("key_path"),
                   "ProgrammaticAccessOnly") is not None:
        return "ProgrammaticAccessOnly"
    return None


def op_for(action, backend, row):
    """(action, 扫描行) → `ops.apply_op` 的 op dict。

    恢复动作的标记值名在这里回读而不是在 UI 线程：`op_for` 由 worker 闭包调用，天然
    落在后台线程（`workers` 的「注册表读写绝不进 UI 线程」纪律）。
    """
    op = {"action": action, "hive": row.get("hive"),
          "key_path": row.get("key_path"), "name": None}
    if action == "restore":
        op["name"] = restore_marker(backend, row)
    return op


def short(value, limit=CMD_MAX):
    """命令显示文本：超长截断并加省略号（全文仍在 tooltip 里）。"""
    text = str(value or "")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def action_label(row):
    """操作按钮文字：已隐藏 → 「恢复」，否则 → 「隐藏」（一行只放一个按钮）。"""
    return "恢复" if row.get("disabled") else "隐藏"


def scope_text(value):
    """scope 键 → 中文（未知键原样返回，畸形行不至于渲染成空白）。"""
    return SCOPE_LABELS.get(str(value or ""), str(value or ""))
