"""right_menu.widgets.page_tabs.custom_rows：自定义项表的纯逻辑层（Qt-free）。

刻意**不 import 任何 Qt**（连 `import_qt` 都没有）：这里只有常量 + 纯函数（吃 dict、出
str / 按钮列表 / 显示行），既能被 `custom_tab.py` 的控件渲染调用，也能被测试直接 import
断言——不需要 QApplication。

单独成文件的首要理由是 250 物理行硬上限：表头列下标、中文标签↔DOM 枚举的**双向**映射、
扩展名文本↔列表的互转、「本行铺哪些按钮」这四块都与控件无关，留在 UI 文件里只会挤掉注释。

**双向映射是本模块的硬需求**：`value()` 要把 combo 下标翻译成 DOM 枚举（`custom_dom
.validate_item` 只认英文枚举），而账本里的历史条目又得翻译回中文显示，两头都要，就地各写
一份必然漂。三个下拉的取值一律**越界回退第一项**（QComboBox 越界在本层不给信号）。

**id 由本层 `new_id()` 生成而 `custom.py` 不生成**：DOM 里 id 就是身份（`save_item` 靠它
upsert），新建时必须有个新身份、编辑时必须保留原身份——那是**对话框层**的决定权，故
`new_id()` 放在这里供 `editor_dialog` 调用（同样 Qt-free，便于钉住「8 位十六进制」契约）。
"""
import uuid

from ...custom_dom import expand_command

#: 结果表头列序（顺序/标题/作用域/扩展名/命令/操作）
HEADERS = ("顺序", "标题", "作用域", "扩展名", "命令", "操作")
#: 表格列下标（与 HEADERS 一一对应）
COL_ORDER, COL_TITLE, COL_SCOPE, COL_EXT, COL_COMMAND, COL_ACTION = 0, 1, 2, 3, 4, 5
#: `tables.fill_table` 的列规格：`(行键, 格式化器)`，与 HEADERS 一一对应；操作列给 `None`
#: 占位（那一列由 `fill_action_cell` 逐行铺按钮，不走文本列）。
COLUMNS = (("order", None), ("title", None), ("scope", None), ("ext", None),
           ("command", None), (None, None))
#: 走 numeric 排序的列：「顺序」显示成字符串的话，「10」会排到「2」前面（NumItem 按 float）
NUMERIC_COLS = (COL_ORDER,)

#: 作用域下拉：显示文字 → DOM `scope`（与 `custom._SCOPE_BASES` 对齐）
SCOPES = (("文件", "file"), ("文件夹", "directory"), ("文件夹背景", "background"),
          ("驱动器", "drive"))
#: 命令类型下拉：显示文字 → DOM `action.kind`（`program` = 让 explorer 跑命令，`open` = 打开）
KINDS = (("运行命令", "program"), ("打开路径/URL", "open"))
#: 位置下拉：显示文字 → DOM `position`（写进注册表 `Position` 值，缺省即 default）
POSITIONS = (("默认", "default"), ("顶部", "top"), ("底部", "bottom"))

#: 作用域列显示文字 → 胶囊色。认不出的 scope 显示「未知作用域/error」，不伪装成正常值——
#: 导入的半截条目不该让人以为它落在了某个已知作用域上。
SCOPE_CHIPS = {"file": ("文件", "info"), "directory": ("文件夹", "info"),
               "background": ("文件夹背景", "info"), "drive": ("驱动器", "warning")}
SCOPE_CHIP_FALLBACK = ("未知作用域", "error")
#: ext_filter 为空时的扩展名列文案（`*` = 所有文件，与 `custom._tree` 的 `*` 根一致）
EXT_ALL = "全部"
#: 操作列按钮：文字 → 动作名（与 `custom_tab._on_action` 的分派一一对应）
ACTION_BUTTONS = (("编辑", "edit"), ("删除", "delete"),
                  ("上移", "move_up"), ("下移", "move_down"))

#: 未加载账本时的默认提示
HINT_IDLE = "自定义项存在本模块账本里（本地 JSON），点「刷新」重读；保存时才写注册表。"
#: 0 条账本条目的提示
EMPTY_HINT = "还没有自定义项。点上方「新建项」添加一条右键菜单命令（只写当前用户）。"
#: group 忙时的统一提示（与 classic_tab 同文案）
HINT_BUSY = "上一项任务还在跑，请等它结束再操作。"
#: 导入/导出的文件过滤器与导出默认文件名（与 `custom.export_items` 的 JSON 结构对应）
FILE_FILTER = "JSON 文件 (*.json)"
EXPORT_NAME = "custom_items.json"


def delete_confirm_text(ident):
    """删除确认框正文（纯文案，故测试能逐字断言「说了什么」而不必开模态框）。"""
    return (f"确认删除「{ident}」？\n\n· 会删掉它在注册表里的全部投影"
            "（子菜单一并删除）\n\n删除后本模块无法一键还原。")


def working_hint(action, ident=""):
    """写动作 → 底部提示文案（`action` 是 `save`/`delete`/`import` 之一）。"""
    if action == "save":
        return f"正在保存「{ident}」…" if ident else "正在新建自定义项…"
    if action == "delete":
        return f"正在删除「{ident}」…"
    return "正在导入自定义项…"


def result_view(result):
    """worker 结果 dict → `(ok, notify 标题, notify 正文, 底部提示)` 四元组。

    把「成功 / 失败 / 畸形结果（None 或非 dict）」的文案口径收在这一处：UI 层三个 `on_*`
    回调只负责把四元组铺到控件上，少一处 `if` 就少一处漂。`save_item` 的 `warnings` 与
    `detail` 拼成一条正文（校验告警不该被 detail 盖掉）。"""
    ok = bool(result.get("ok")) if isinstance(result, dict) else False
    detail = (result.get("detail") or "") if isinstance(result, dict) else ""
    warnings = (result.get("warnings") or []) if isinstance(result, dict) else []
    body = "；".join([w for w in warnings + [detail] if w]).strip()
    return ok, ("操作完成" if ok else "操作失败"), body, (
        detail or ("操作已完成。" if ok else "操作失败。"))


def text(value):
    """任意值 → 去除首尾空白的字符串；`None` → `""`（表格里显示空白而不是「None」）。"""
    return "" if value is None else str(value).strip()


def new_id():
    """新建项的身份：`uuid4().hex[:8]`（与 `custom` 的 slug 前 6 位配套，短且唯一）。"""
    return uuid.uuid4().hex[:8]


def item_id(item):
    """条目 → id 文本；非 dict / 缺字段一律 `""`（畸形行不能让渲染崩在 UI 线程上）。"""
    return text(item.get("id")) if isinstance(item, dict) else ""


def find_index(items, ident):
    """账本条目列表 → 目标 id 的下标；找不到（或 id 为空）一律 -1（`move` 的边界判定用它）。"""
    target = text(ident)
    if not target:
        return -1
    return next((i for i, item in enumerate(list(items or []))
                 if item_id(item) == target), -1)


def find_item(items, ident):
    """账本条目列表 → 命中 id 的那条；找不到返回 None（编辑路径的「条目已消失」判定）。"""
    items = list(items or [])
    index = find_index(items, ident)
    return items[index] if index >= 0 else None


def parse_ext_filter(raw):
    """输入框文本 → `ext_filter` 列表：`"py, md"` → `[".py", ".md"]`。

    按 `,` `;` 空白三种分隔符切，去空白，缺前缀的补 `.`；空串 / 全空白 → `[]`（= 全部）。
    逗号与中文顿号也一并吃掉（用户从文档里抄 `py、md` 是常事）。不合法形状留给
    `validate_item` 报错，本层只做规范化不做判断。"""
    out = []
    for chunk in text(raw).replace("、", ",").replace(";", ",").replace(
            " ", ",").split(","):
        piece = chunk.strip().lstrip(".")
        if piece:
            out.append(f".{piece}")
    return out


def format_ext_filter(exts):
    """`ext_filter` 列表 → 输入框文本：`[".py", ".md"]` → `"py, md"`（去掉重复的点号）。"""
    if not isinstance(exts, (list, tuple)):
        return ""
    return ", ".join(text(ext).lstrip(".") for ext in exts if text(ext))


def _picked(pairs, index):
    """下拉下标 → DOM 枚举值；越界回退第一项（`-1` 之类只可能来自测试或畸形 item）。"""
    return pairs[index][1] if 0 <= index < len(pairs) else pairs[0][1]


def scope_value(index):
    """作用域下拉下标 → DOM `scope`。"""
    return _picked(SCOPES, index)


def kind_value(index):
    """命令类型下拉下标 → DOM `action.kind`。"""
    return _picked(KINDS, index)


def position_value(index):
    """位置下拉下标 → DOM `position`。"""
    return _picked(POSITIONS, index)


def _index_of(pairs, value):
    """DOM 枚举值 → 下拉下标；未知值回退 0（打开对话框时至少停在第一项而不是空白）。"""
    target = text(value).strip().lower()
    for index, (_, enum) in enumerate(pairs):
        if enum == target:
            return index
    return 0


def scope_index(value):
    """DOM `scope` → 作用域下拉下标（编辑历史条目时用来预选）。"""
    return _index_of(SCOPES, value)


def kind_index(value):
    """DOM `action.kind` → 命令类型下拉下标（兼容 `command`/`url` 两个历史别名）。"""
    return _index_of(KINDS, {"command": "program", "url": "open"}.get(
        text(value).strip().lower(), value))


def position_index(value):
    """DOM `position` → 位置下拉下标。"""
    return _index_of(POSITIONS, value)


def scopetext(value):
    """DOM `scope` → 作用域列显示文字（认不出的值原样显示，让人看见账本里存了什么）。"""
    enum = text(value).strip().lower()
    return SCOPE_CHIPS.get(enum, (enum or "未知作用域", "error"))[0]


def commandtext(item):
    """命令列文本：`custom_dom.expand_command` 的可读展开（**仅预览**，注册表里仍是模板）。"""
    return expand_command(item) if isinstance(item, dict) else ""


def display_rows(items):
    """账本条目 → 表格显示行（`HEADERS` 前五列的文本 + 原始 `item` 透传给操作列）。

    「收下这批条目」与「把手上这批条目画出来」在 `custom_tab` 里分开同 scan/shellnew，
    本函数只负责后者里与控件无关的那半：所有列文本都在这里算好，UI 层逐列 `row.get` 即可。
    """
    rows = []
    for index, item in enumerate(list(items or [])):
        item = item if isinstance(item, dict) else {}
        rows.append({
            "order": str(index + 1),
            "title": text(item.get("title")),
            "scope": scopetext(item.get("scope")),
            "ext": format_ext_filter(item.get("ext_filter")) or EXT_ALL,
            "command": commandtext(item),
            "item": item,
        })
    return rows


def actions_for(row):
    """本行的操作按钮 `[(文字, (动作, id))]`：编辑 / 删除 / 上移 / 下移。

    上移下移对首尾行照样给——`move` 自己按越界返 False，用户点了只会看到一次无动作的
    点击；反过来把首尾行的按钮藏掉，就得让 UI 多知道一个「我在第几行」的状态。
    """
    ident = item_id(row.get("item")) if isinstance(row, dict) else ""
    return [(text, (action, ident)) for text, action in ACTION_BUTTONS]


def hint_for(count):
    """渲染完成后的提示文案（0 条走含排查口径的 `EMPTY_HINT`）。"""
    if not count:
        return EMPTY_HINT
    return f"共 {count} 项；行尾可编辑/删除/调整顺序，改顺序只动账本、不重写注册表。"
