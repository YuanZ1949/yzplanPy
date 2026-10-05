r"""right_menu 自定义项的**纯 DOM 层**：取值兜底 / 校验 / 命令模板展开 / slug。

从 `custom.py` 拆出（250 物理行上限）。DOM 形状见 spec §5.6（`id/title/icon/scope/
ext_filter/hive/extended/position/action{kind,target,args,workdir}/children`），本模块只做
**不碰注册表、不碰账本**的纯函数：校验危险写法、展开命令模板（**仅预览/告警**）、生成注册表
shell 键名 slug。写通道（投影路径、ops 构造、提权、账本）在 `custom.py`；依赖方向单向
（`custom → custom_dom`，本文件绝不反向 import，否则两条 import 路径互为前提）。

Qt-free：只用 stdlib + `shellnew.EXT_RE`（扩展名正则单一真源，shellnew 亦 Qt-free）。
"""
import re

from .shellnew import EXT_RE

__all__ = ["validate_item", "expand_command", "slugify"]

_KINDS = ("command", "program", "url", "open")
_SCOPES = ("file", "directory", "background", "drive")   # 与 custom._SCOPE_BASES 对齐
_SLUG_UNSAFE = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff]")


# 取值兜底：历史条目缺字段 / 半截导入 / 非字典条目一律不抛（`_sub` 是唯一取值入口）
def _text(value):
    return "" if value is None else str(value)


def _sub(item, key, kind=str):
    """`item[key]` → `kind` 类型；缺字段 / 类型不符 / 条目非字典都返回兜底值。"""
    value = item.get(key) if isinstance(item, dict) else None
    return value if isinstance(value, kind) else kind()


def _children(item):
    return [kid for kid in _sub(item, "children", list) if isinstance(kid, dict)]


def _command(item):
    """`action.target + " " + action.args`：写进 `command` 默认值的**原始模板**。"""
    action = _sub(item, "action", dict)
    return (_sub(action, "target") + " " + _sub(action, "args")).strip()


# ── 校验（spec §5.6 危险校验：errors 拒绝保存，warnings 只提示）─────────────
def validate_item(item):
    """DOM → `{"ok", "errors", "warnings"}`；非字典入参 → 一条 error。"""
    if not isinstance(item, dict):
        return {"ok": False, "errors": ["项目数据非法"], "warnings": []}
    errors, warnings, pending = [], [], [item]   # 显式栈：DOM 的 children 允许任意深度
    while pending:
        node = pending.pop()
        action = _sub(node, "action", dict)
        kind, target = _sub(action, "kind").strip().lower(), _sub(action, "target").strip()
        kids, text = _children(node), f"{_sub(action, 'target')} {_sub(action, 'args')}"
        pending += kids
        if kind and kind not in _KINDS:
            errors.append(f"不支持的命令类型: {kind}")
        if not kids and not target:             # 子菜单不需要自己的命令
            errors.append("目标不能为空")
        for found in re.findall(r"%.", text):
            if found in ("%1", "%*", "%V"):
                if f'"{found}"' not in text:    # 已加引号 → 含空格的路径也安全
                    warnings.append(f"占位符 {found} 未加引号，含空格的路径会被拆成多个参数")
            else:
                warnings.append(f"未识别的占位符 {found}（只支持 %1 / %* / %V）")
        if "cmd /c" in text.casefold():
            warnings.append("检测到 cmd /c 模板，请确认示例命令能按预期执行")
    scope = _sub(item, "scope").strip().lower() or "file"
    if scope != "file" and scope not in _SCOPES:
        errors.append(f"不支持的作用域: {scope}")
    for ext in (_sub(item, "ext_filter", list) if scope == "file" else []):  # ext 仅 file 有意义
        if not EXT_RE.fullmatch(_text(ext).strip()):     # fullmatch：$ 会吃进换行
            errors.append(f"扩展名格式无效: {_text(ext)}")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def expand_command(item, *, selected=None, current_dir=None):
    """`action` 模板 → 可读命令（**仅预览/告警**）：`%1` = 首个选中项（多选取第一个）、
    `%*` = 全部选中项、`%V` = 当前目录；取值缺失时占位符**原样保留**。"""
    selected = [_text(path) for path in (selected or []) if _text(path)]
    template = _command(item)
    for placeholder, values in (("%1", selected[:1]), ("%*", selected),
                                ("%V", [_text(current_dir)] if current_dir else [])):
        if values:
            # 已被双引号紧邻包裹的换裸路径（否则会写出 `""…""`），否则含空格则补引号
            bare = f'"{placeholder}"' in template
            template = template.replace(
                placeholder, " ".join(v if bare or " " not in v else f'"{v}"' for v in values))
    return template


def slugify(item):
    """`<净标题>_<id[:6]>`：注册表 shell 键名，必须**确定性**（否则 sync 不幂等）。"""
    title = _SLUG_UNSAFE.sub("_", _sub(item, "title").strip())[:32] or "item"
    return f"{title}_{_sub(item, 'id').strip()[:6]}"
