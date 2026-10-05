r"""right_menu 自定义项：注册表投影 + CRUD + JSON 导入导出（写通道）。

DOM 的**纯函数层**（校验 / 命令模板展开 / slug）拆在 `custom_dom.py`（250 物理行上限）；本模块
只管写——把该项**投影**成 `Software\Classes\...\shell\<slug>` 那几棵键树：先算出该项的**全部**
投影路径 delete_tree 再重写值，故改作用域 / 改扩展名过滤 / 改标题都会自动清掉旧投影，sync 可
反复执行（幂等）。命令模板（`%1`/`%*`/`%V`）**写进注册表时原样保留**——展开是 explorer 的活，
`expand_command` 只是同源实现的预览/告警。

跨任务契约：**Qt-free**；**调用时取模块属性**（按 `store.xxx()` / `elevate.xxx()` 调用，否则
monkeypatch 拦不到「UAC 被取消」）；**顺序是硬约定** 备份快照 → 写（删旧+建新）→ 回读 → 记账本
（写没落地就撤回账本条目，并尽力重建旧投影）；**HKCU 直写 / HKLM 走提权**（父进程直写 HKLM
是静默无效的），且 **ops 按 hive 分组**执行——旧投影在 HKLM 而新项在 HKCU 时，那几条删除也必须
走提权通道。`validate_item` / `expand_command` / `slugify` 从 `custom_dom` **原样转出**，
下游（Task 17 的编辑器、workers）仍走 `custom.xxx` 这一条导入路径。
"""
import json

from . import elevate, store
from .custom_dom import (_children, _command, _sub, _text, expand_command, slugify,
                         validate_item)

__all__ = ["validate_item", "expand_command", "slugify", "save_item", "delete_item",
           "sync_all", "export_items", "import_items"]

_CLASSES = r"Software\Classes"
_SCOPE_BASES = {"directory": "Directory", "background": r"Directory\Background",
                "drive": "Drive"}            # scope（根）→ 其 shell 键的父键
_HIVES = ("hkcu", "hklm")                    # 顺序即执行顺序：本地先、提权后
_ERROR_TEXTS = {"cancelled": "已取消（UAC 被拒绝），未做任何修改",
                "timeout": "未收到提权结果，请稍后重试",
                "write_failed": "写入未生效（可能被安全软件拦截）"}


def _hive(item):
    """item → hive；缺失 / 不认识的 hive 一律按 HKCU 处理（绝不凭空写 HKLM）。"""
    hive = _sub(item, "hive").strip().lower()
    return hive if hive in _HIVES else "hkcu"


def _result(ok, detail):
    return {"ok": bool(ok), "detail": str(detail)}


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
        if not isinstance(out, dict):           # 契约外的返回（None / 列表…）按失败算
            return _result(False, "提权作业失败")
        ok = bool(out.get("ok"))
        return _result(ok, "已写入" if ok else _ERROR_TEXTS.get(out.get("error"), "提权作业失败"))
    failed = next((r for r in elevate.exec_ops(backend, ops) if not r.get("ok")), None)
    return _result(failed is None, "已写入" if failed is None
                   else _ERROR_TEXTS.get(failed.get("error"), "写入未生效"))


def _sync_item(backend, new_item, old_item=None, *, store_mod=None):
    """重建一个 item 的投影：先删全部旧/新投影路径再重写值（漏删 = 菜单里的孤儿项）。

    **按 hive 分组**执行：旧投影在 HKLM 而新项在 HKCU 时，那几条删除也必须走提权通道（走本地
    会静默无效，HKLM 侧就留下一份再也点不到的孤儿项）。组间按 `_HIVES` 顺序，本地先、提权后
    ——本地那组失败时就别再为它弹一次 UAC。
    """
    hive = _hive(new_item)
    stale = [(h, path) for item, h in ((old_item, _hive(old_item)), (new_item, hive))
             for path, _, _ in _tree(item)]
    groups = {}
    for h, path in dict.fromkeys(stale):       # 旧/新投影可能落在同一键，删除去重
        groups.setdefault(h, []).append(elevate.delete_tree_op(h, path))
    for path, node, parent in _tree(new_item):
        groups.setdefault(hive, []).extend(_node_ops(hive, path, node, parent))
    if not groups:
        return _result(True, "无需写入")
    for h in _HIVES:
        if not groups.get(h):
            continue
        out = _apply(h, groups[h], backend)
        if not out["ok"]:
            return out
    return _result(True, "已写入")


# ── 账本 CRUD + JSON 导出/导入（id 即身份；upsert 追加保序，写失败回滚）─────
def _split(items, ident):
    """按 id 拆成 `(命中项或 None, 其余条目)`——upsert / 删除 / 回滚共用一份口径。"""
    hit = [i for i in items if _sub(i, "id").strip() == ident]
    return (hit[0] if hit else None), [i for i in items if _sub(i, "id").strip() != ident]


def save_item(backend, item, *, store_mod=None):
    """校验 → 备份 → 落账本 → 重建投影 → `{"ok", "detail", "warnings"}`。

    改前的样子在 upsert **之前**从账本快照取（它决定要清哪些旧投影），**备份也必须在改账本之前**
    ——快照得是「改前」的账本，否则它还原不出任何东西。写失败时账本条目回滚，并尽力重建旧投影
    （仅本地 hkcu：失败路径里绝不弹第二次 UAC）。
    """
    report, ledger = validate_item(item), store_mod or store
    if not report["ok"]:
        return dict(_result(False, "；".join(report["errors"])), warnings=report["warnings"])
    old, rest = _split(ledger.get_custom_items(), _sub(item, "id").strip())
    ledger.backup_snapshot(f"custom {_sub(item, 'id').strip()}")
    if not ledger.set_custom_items(rest + [item]):
        return dict(_result(False, "账本写入失败"), warnings=report["warnings"])
    out = _sync_item(backend, item, old, store_mod=store_mod)
    if not out["ok"]:
        # 写没落地就撤回账本：记下一次从未发生的改动，比一次写失败更难收拾
        ledger.set_custom_items(rest + ([old] if old else []))
        if old and _hive(old) == "hkcu":
            _sync_item(backend, old, None, store_mod=store_mod)   # 旧投影已删，补回去
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
    ledger = store_mod or store
    ledger.backup_snapshot("custom sync_all")    # 只写注册表也要先留快照（spec L172）
    for item in ledger.get_custom_items():
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
    ledger.backup_snapshot("custom import")      # 改账本之前先留快照
    if not ledger.set_custom_items(items):
        return _result(False, "账本写入失败")
    out = sync_all(backend, store_mod=store_mod)
    return _result(out["ok"], out["detail"] + ("；跳过 " + "，".join(skipped) if skipped else ""))
