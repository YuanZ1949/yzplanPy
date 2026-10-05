r"""right_menu 自定义右键项：DOM 校验 / 命令模板展开 / 注册表投影 / CRUD。

DOM（spec §5.6：id/title/icon/scope/ext_filter/hive/extended/position/action/children）存
在账本里，本模块把它**投影**成 `Software\Classes\...\shell\<slug>` 那几棵键树：先算出该项的
**全部**投影路径 delete_tree 再重写值，故改作用域 / 改扩展名过滤 / 改标题都会自动清掉旧投影，
sync 可反复执行（幂等）。命令模板（`%1`/`%*`/`%V`）**写进注册表时原样保留**——展开是
explorer 的活，`expand_command` 只是同源实现的预览/告警。**顺序是硬约定** 校验 → 备份 →
写 → 回读 → 记账本（写没落地就撤回账本条目）；**HKCU 直写 / HKLM 走提权**（父进程直写 HKLM
是静默无效的）；**Qt-free**；**调用时取模块属性**（否则 monkeypatch 拦不到「UAC 被取消」）。
"""
import json, re

from . import elevate, store
from .shellnew import EXT_RE          # 扩展名正则与 ShellNew 共用一份，避免两套口径

__all__ = ["validate_item", "expand_command", "slugify", "save_item", "delete_item",
           "sync_all", "export_items", "import_items"]

_CLASSES = r"Software\Classes"
_SCOPE_BASES = {"directory": "Directory", "background": r"Directory\Background", "drive": "Drive"}
_KINDS, _HIVES = ("command", "program", "url", "open"), ("hkcu", "hklm")
_SLUG_UNSAFE = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff]")
_ERROR_TEXTS = {"cancelled": "已取消（UAC 被拒绝），未做任何修改",
                "timeout": "未收到提权结果，请稍后重试",
                "write_failed": "写入未生效（可能被安全软件拦截）"}


# 取值兜底：历史条目缺字段 / 半截导入 / 非字典条目一律不抛（`_sub` 是唯一取值入口）
def _text(value):
    return "" if value is None else str(value)


def _sub(item, key, kind=str):
    """`item[key]` → `kind` 类型；缺字段 / 类型不符 / 条目非字典都返回兜底值。"""
    value = item.get(key) if isinstance(item, dict) else None
    return value if isinstance(value, kind) else kind()


def _children(item):
    return [kid for kid in _sub(item, "children", list) if isinstance(kid, dict)]


def _hive(item):
    """item → hive；缺失 / 不认识的 hive 一律按 HKCU 处理（绝不凭空写 HKLM）。"""
    hive = _sub(item, "hive").strip().lower()
    return hive if hive in _HIVES else "hkcu"


def _command(item):
    """`action.target + " " + action.args`：写进 `command` 默认值的**原始模板**。"""
    action = _sub(item, "action", dict)
    return (_sub(action, "target") + " " + _sub(action, "args")).strip()


def _result(ok, detail):
    return {"ok": bool(ok), "detail": str(detail)}


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
    if scope != "file" and scope not in _SCOPE_BASES:
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


# ── 投影：路径计算 + ops 构造（注册表里永远是未展开的模板）──────────────────
def _tree(item, parent=None):
    r"""递归展开子树 → `[(完整键路径, 节点, 是否子菜单父键)]`。根节点按 scope 定位（`file`
    无过滤 → `*`，带过滤 → 每个 `SystemFileAssociations\<ext>`）；子项挂在**父键自己的**
    `shell` 子树下（explorer 认的子菜单结构），每节点用自己 title+id 的 slug。"""
    if not isinstance(item, dict):
        return []                             # 半截导入的非字典条目：无可投影的子树
    if parent is None:
        scope = _sub(item, "scope").strip().lower() or "file"
        exts = [_text(e).strip() for e in _sub(item, "ext_filter", list) if _text(e).strip()]
        base = _SCOPE_BASES.get(scope)
        bases = ([_CLASSES + r"\*"] if scope == "file" and not exts else
                 [f"{_CLASSES}\\SystemFileAssociations\\{e}" for e in exts] if scope == "file"
                 else [_CLASSES + "\\" + base] if base else [])
        paths = [f"{root}\\shell\\{slugify(item)}" for root in bases]
    else:
        paths = [f"{parent}\\shell\\{slugify(item)}"]
    kids = _children(item)
    out = [(path, item, bool(kids)) for path in paths]
    return out + [row for path in paths for kid in kids for row in _tree(kid, path)]


def _node_ops(hive, path, node, is_parent):
    """一个节点的 set 原语（值表里 None = 不写）；子菜单父键不写 `command`。"""
    values = [("MUIVerb", _sub(node, "title")), ("Icon", _sub(node, "icon").strip() or None),
              ("SubCommands", "" if is_parent else None),
              ("Extended", "" if node.get("extended") else None),
              ("Position", {"top": "Top", "bottom": "Bottom"}.get(_sub(node, "position").lower()))]
    ops = [elevate.set_op(hive, path, name, value) for name, value in values if value is not None]
    if _command(node) and not is_parent:        # 子菜单的 explorer 只认 SubCommands
        ops.append(elevate.set_op(hive, path + r"\command", "", _command(node)))
    return ops


def _apply(hive, ops, backend):
    """执行一批原语 → 结果 dict：hkcu 本地 `exec_ops`（内部逐条写后回读），hklm 交提权作业。"""
    if not ops:
        return _result(True, "无需写入")
    if hive == "hklm":                         # 父进程直写 HKLM 是静默无效的
        try:
            out = elevate.run_job({"ops": ops})
        except Exception:                      # 作业通道异常也不拖垮 GUI 线程
            return _result(False, "提权作业失败")
        ok = isinstance(out, dict) and bool(out.get("ok"))
        return _result(ok, "已写入" if ok else _ERROR_TEXTS.get(out.get("error"), "提权作业失败"))
    failed = next((r for r in elevate.exec_ops(backend, ops) if not r.get("ok")), None)
    return _result(failed is None, "已写入" if failed is None
                   else _ERROR_TEXTS.get(failed.get("error"), "写入未生效"))


def _sync_item(backend, new_item, old_item=None, *, store_mod=None):
    """重建一个 item 的投影：先删全部旧/新投影路径再重写值（漏删 = 菜单里的孤儿项）。"""
    hive = _hive(new_item)
    stale = [(h, path) for item, h in ((old_item, _hive(old_item)), (new_item, hive))
             for path, _, _ in _tree(item)]
    ops = [elevate.delete_tree_op(h, p) for h, p in dict.fromkeys(stale)]
    ops += [op for path, node, parent in _tree(new_item)
            for op in _node_ops(hive, path, node, parent)]
    (store_mod or store).backup_snapshot(f"custom {_sub(new_item, 'id').strip()}")
    return _apply(hive, ops, backend)


# ── 账本 CRUD + JSON 导出/导入（id 即身份；upsert 追加保序，写失败回滚）─────
def _split(items, ident):
    """按 id 拆成 `(命中项或 None, 其余条目)`——upsert / 删除 / 回滚共用一份口径。"""
    hit = [i for i in items if _sub(i, "id").strip() == ident]
    return (hit[0] if hit else None), [i for i in items if _sub(i, "id").strip() != ident]


def save_item(backend, item, *, store_mod=None):
    """校验 → 落账本 → 重建投影 → `{"ok", "detail", "warnings"}`；写失败回滚账本条目。"""
    report, ledger = validate_item(item), store_mod or store
    if not report["ok"]:
        return dict(_result(False, "；".join(report["errors"])), warnings=report["warnings"])
    old, rest = _split(ledger.get_custom_items(), _sub(item, "id").strip())   # 改前的快照
    if not ledger.set_custom_items(rest + [item]):
        return dict(_result(False, "账本写入失败"), warnings=report["warnings"])
    out = _sync_item(backend, item, old, store_mod=store_mod)
    if not out["ok"]:
        # 写没落地就撤回账本：记下一次从未发生的改动，比一次写失败更难收拾
        ledger.set_custom_items(rest + ([old] if old else []))
    return dict(out, warnings=report["warnings"])


def delete_item(backend, item_id, *, store_mod=None):
    """删一个自定义项：删掉它的全部投影 → 从账本移除；条目不存在时幂等报成功。"""
    ledger, ident = store_mod or store, _text(item_id).strip()
    item, rest = _split(ledger.get_custom_items(), ident)
    ops = [elevate.delete_tree_op(_hive(item), path) for path, _, _ in _tree(item)]
    ledger.backup_snapshot(f"custom {ident}")      # 写任何值之前先备份（spec L172）
    out = _apply(_hive(item), ops, backend)
    if not out["ok"]:
        return out                            # 键没删掉 → 账本条目原样留着
    ledger.set_custom_items(rest)
    return _result(True, "已删除")


def sync_all(backend, *, store_mod=None):
    """按账本重建全部自定义项的投影 → `{"ok", "detail"}`；任一项失败即整体失败。"""
    for item in (store_mod or store).get_custom_items():
        out = _sync_item(backend, item, item, store_mod=store_mod)
        if not out["ok"]:
            return _result(False, f"{_sub(item, 'title') or _sub(item, 'id')}：{out['detail']}")
    return _result(True, "已重建全部自定义项")


def export_items(path):
    """把账本里的自定义项写成 `{"schema":1,"items":[...]}` JSON → `{"ok", "detail"}`。"""
    payload = {"schema": 1, "items": store.get_custom_items()}
    try:
        with open(_text(path), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except (OSError, TypeError, ValueError):
        return _result(False, "导出失败：文件不可写")
    return _result(True, f"已导出 {len(payload['items'])} 项")


def import_items(backend, path, *, store_mod=None):
    """导入 JSON：逐条校验（非法**跳过**并在 detail 汇报）→ 按 id upsert → sync_all（跳过
    而非整份拒绝：手改过的导出里往往只有一两条坏了）。"""
    ledger = store_mod or store
    try:
        with open(_text(path), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return _result(False, "导入失败：文件不可读或不是合法 JSON")
    entries = payload if isinstance(payload, list) else _sub(payload, "items", list)
    items, skipped = list(ledger.get_custom_items()), []
    for entry in entries:
        report = validate_item(entry)
        if report["ok"]:
            items = _split(items, _sub(entry, "id").strip())[1] + [entry]
        else:
            skipped.append(f"{_sub(entry, 'title') or '?'}：{report['errors'][0]}")
    if not ledger.set_custom_items(items):
        return _result(False, "账本写入失败")
    out = sync_all(backend, store_mod=store_mod)
    return _result(out["ok"], out["detail"] + ("；跳过 " + "，".join(skipped) if skipped else ""))
