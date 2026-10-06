r"""right_menu.widgets.page_tabs.settings_rows：设置标签的**纯决策层**（零 Qt import）。

表头与文案、快照文件名拆解、备份行组装、动作勾选 ↔ 勾选清单的换算、两个 worker 的返回值
视图——全在本文件。它们是「这里显示什么 / 到底要发哪份清单」的唯一决策点：错了 UI 层没有任何
编译期信号（按钮照铺、表照画、`install_yzmenu` 照收一份不是用户意图的清单），故与 scan /
shellnew / custom 同包同构地把纯逻辑抽出，测试可直接断言。

**Qt-free 是硬要求**：本文件只 import `os`，故任何不建 QApplication 的测试进程都能 import 它。

两处**反直觉但刻意的**决策写在这里，别顺手"修正"：

  * `wanted_actions` 不去重、不剔除空项、不在空清单时替用户补一个动作——空清单原样发出，由
    `yzmenu._validate` 在任何写入之前拒掉，UI 再把「至少选择一个动作」当普通失败提示展示。
    这里"好心"补一个，装出来的菜单就多出用户没要求的那一行。
  * `checked_by_state` 在**未安装**时一律返回全勾：`get_yzmenu_state` 只报「实况有哪些子键」，
    未安装时它是空的，而「空勾选表 + 主开关」= 装出一个点开什么都没有的空壳菜单。
"""

import os

__all__ = ["HEADERS", "BACKUP_COLUMNS", "BACKUP_ACTIONS", "COL_ACTION", "OPEN_TEXT",
           "BACKUP_SUFFIX", "HINT_IDLE", "HINT_BUSY", "NOTE_RESTORE", "NOTE_CLASSIC",
           "BACKUP_CARD_TITLE", "split_stem", "backup_rows", "wanted_actions",
           "checked_by_state", "is_restore_result", "result_view", "restore_view",
           "working_hint"]

#: 备份表表头（三列：「操作」列每行铺一枚按钮）
HEADERS = ("时间", "原因", "操作")
#: 表头 → `fill_table` 的列规格（末列 `(None, None)` = 让位给 action_col）
BACKUP_COLUMNS = (("time", None), ("reason", None), (None, None))
#: 「操作」列下标（`fill_table` 的 action_col）
COL_ACTION = 2
#: 行尾按钮文字。**开的是快照所在目录**，不是打开某一份快照（那是个 JSON 账本）
OPEN_TEXT = "打开目录"
#: 行尾按钮铺法（`fill_table` 的 actions：文字 + 「从行取参数」的函数）
BACKUP_ACTIONS = [(OPEN_TEXT, lambda row: row["path"])]
#: 快照文件后缀：只认这一种扩展名，其余（临时文件、说明文件）一律不进表
BACKUP_SUFFIX = ".json"
#: 底部提示的初始文案
HINT_IDLE = "改动要重启资源管理器才可见；「一键还原」撤销的是账本里记录的每一类改动。"
#: group 忙时的统一提示（三个写动作共用）
HINT_BUSY = "上一项任务还在跑，请等它结束再操作。"
#: 两块卡的固定说明（先说清还原会动什么，再说清经典菜单的联动）
NOTE_RESTORE = ("一键还原逐条撤销账本记录的改动：隐藏的右键项、隐藏的「新建」菜单项、"
                "自定义菜单项、YZplan 右键子菜单。")
NOTE_CLASSIC = "若经典菜单处于开启状态也会一并关闭。"
#: 「备份」卡的标题兼边界说明。放进标题而不另起一个说明 label：同一句话说两遍，用户只会以为
#: 缺功能。快照的语义是「改动**之前**的账本」，只作留档——本表因此**不做**恢复单份，那要按条目
#: 重放，与「一键还原」不是一回事。
BACKUP_CARD_TITLE = "备份 · 每次改动前的账本快照，只作留档"


# ── 快照文件名 ──────────────────────────────────────────────────────────
def split_stem(name):
    """快照文件名 → (时间, 原因)。文件名形如 `20261005_141530_disable_hkcu.json`。

    时间戳**自身含一个下划线**，故按前两个下划线切（`split("_", 2)`：前两段拼回时间，其余全归
    原因）。不足两段时整段当时间、原因空——外部塞进目录的杂文件因此不会被解析成乱码。"""
    stem = name[:-len(BACKUP_SUFFIX)] if str(name or "").endswith(BACKUP_SUFFIX) else name
    parts = stem.split("_", 2)
    if len(parts) < 2:
        return stem, ""
    return "_".join(parts[:2]), (parts[2] if len(parts) > 2 else "")


def backup_rows(names, directory):
    """目录里的文件名列表 → 备份表行 dict（`time`/`reason`/`path`），新→旧。

    排序直接按文件名倒序：文件名以时间戳开头，故零额外 `stat` 就得到新→旧（**只有 mtime 才
    严格**，但快照是本模块自己写的、名字即顺序，够用）。调用方负责 try/except 取 `names`
    （目录可能不存在——那不是错误，没有快照就是空表）。"""
    rows = []
    for name in sorted((n for n in (names or []) if str(n).endswith(BACKUP_SUFFIX)),
                       reverse=True):
        stamp, reason = split_stem(name)
        rows.append({"time": stamp, "reason": reason,
                     "path": os.path.join(str(directory or ""), name)})
    return rows


# ── 勾选 ⇄ 动作清单 ────────────────────────────────────────────────────
def wanted_actions(actions, checked):
    """`(动作名列表, 勾选布尔列表)` → 真正要装的动作清单（保持 actions 原序）。

    **不去重、不剔除空项、空清单原样返回**（见模块 docstring）。`zip` 天然截断到较短的一边，
    控件数与 `ACTIONS` 不一致时不会 IndexError——多出来的控件按"没勾"处理。"""
    return [a for a, on in zip(actions or [], checked or []) if on]


def checked_by_state(actions, installed, present):
    """`(动作名列表, 是否已装, 已装动作名序列)` → 每项是否勾选。

    动作名比较统一 `casefold`（注册表键名大小写不敏感）；未安装时一律全勾（见模块 docstring）。"""
    names = list(actions or [])
    if not installed:
        return [True] * len(names)
    seen = {str(name).casefold() for name in (present or [])}
    return [str(action).casefold() in seen for action in names]


# ── worker 返回值视图 ──────────────────────────────────────────────────
def is_restore_result(result):
    """结果形状是不是一键还原的（`{"ok","report":[...]}`）——三个写动作的分派判据。"""
    return isinstance(result, dict) and isinstance(result.get("report"), list)


def result_view(result):
    """`{"ok","detail"}` → `(ok, 标题, 正文, 提示)`。开/关子菜单共用这一个视图。

    契约外的返回值（非 dict）一律落 `ok=False`。**「至少选择一个动作」是返回值不是异常**，与
    其它失败同等对待：一条非阻塞提示即可，不必弹模态框把用户从工作流里拽出去。"""
    ok = bool(result.get("ok")) if isinstance(result, dict) else False
    detail = (result.get("detail") or "") if isinstance(result, dict) else ""
    return ok, ("操作完成" if ok else "操作失败"), detail, \
        (detail or ("操作已完成。" if ok else "操作失败。"))


def restore_view(result):
    """`{"ok","report":[{"kind","ok","detail"}]}` → `(ok, 标题, 正文, 提示)`（与 `result_view` 同形）。

    报的是**条数**（用户要的是「动了多少处」），失败条数顺带说明「留在账本里可重试」——把每条
    detail 堆进 InfoBar 会把一屏挤爆，逐条明细已经进了 `restore_points`。空 report 有专门
    文案：空账本不是错误，但得让用户明白「没东西可还原」而不是「点了没反应」。"""
    report = result.get("report") if isinstance(result, dict) else None
    report = list(report) if isinstance(report, list) else []
    ok = bool(result.get("ok")) if isinstance(result, dict) else False
    failed = [row for row in report
              if not (row.get("ok") if isinstance(row, dict) else False)]
    if not report:
        body = "账本里没有可还原的改动。"
    else:
        body = f"共处理 {len(report)} 条，失败 {len(failed)} 条。"
        if failed:
            body += "失败的条目留在账本里，可再试一次。"
    return ok, ("已还原" if ok else "部分未还原"), body, body


def working_hint(kind, count=0):
    """三个写动作的「正在…」提示（纯文案；`kind` 取 install/uninstall/restore）。

    把动作名与动作数放进文案而不是塞进 `label`：任务标签是日志用的，展示语要随动作数变。"""
    if kind == "uninstall":
        return "正在卸载「YZplan」右键子菜单…"
    if kind == "install":
        return f"正在安装「YZplan」右键子菜单（{count} 个动作）…"
    return "正在还原账本里记录的改动…"
