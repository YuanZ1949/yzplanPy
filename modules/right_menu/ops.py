"""right_menu 统一操作层：隐藏（disable）/ 还原（restore）/ 删除（delete）三个原语动作。

这是 right_menu **唯一的写操作网关**——UI 标签页、workers、MCP slice 全部只调
`apply_op(backend, op)`，不自己碰 `registry_backend` 与 `store`，否则「备份 → 写 → 回读
→ 记账本」的顺序会在每个调用点各写一遍并各自漂移。

op 形状：
    {"action": "disable"|"restore"|"delete", "hive": "hkcu"|"hklm", "key_path": str,
     "name": str|None, "original": str|None, "builtin": bool}
  * `name` 是**隐藏标记的值名**（缺省 `LegacyDisable`；也可指定
    `ProgrammaticAccessOnly` 等 scan 认的其它标记）。隐藏写它、还原删它，两侧同源——
    写成硬编码 `LegacyDisable` 而还原删 `name`，带 name 的往返就会删错值名。
  * `original` 是隐藏前该值名上已有的值；还原时先删标记、再把它写回去（顺序反了等于
    没还原）。它是账本条目的一部分（store 的 disabled 桶带 original 键）。
  * `builtin` 只被 delete 用：系统内建伪项（无命令无子项）没有可恢复的来源，禁止删除。

跨任务契约：
  * **Qt-free**：只用 stdlib + 本包 `store` / `elevate`（两者都 Qt-free），本文件可能
    在 `--elevated-job` 早退通道的 import 链上被拉进来。
  * **依赖方向单向**：`ops → elevate / store`，反向都不 import 本文件。
  * **调用时取模块属性**：以 `from . import elevate, store` 导入并**在函数体内按
    `store.xxx()` / `elevate.xxx()` 调用**——`from .elevate import run_job` 那样的直接
    绑定会在 import 时把名字钉死，monkeypatch 拦截不到，测试也就测不了「UAC 被取消」。
  * **永不抛**：参数非法/后端异常/提权作业异常一律降级成 `{"ok": False, "detail": ...}`。
  * **写后回读**：`RegistryBackend` 是 never-raise 契约（HKLM 未提权的写入会静默无声），
    「无权限」与「成功」在返回值上无法区分，只有回读能。直写（hkcu）路径因此每次写完
    都回读校验，不落地即报失败；提权路径的回读在子进程 `elevate_ops.exec_ops` 里做。
  * **账本只在写成功后动**：写失败/被取消时账本绝不能留下没发生的改动。
"""
from . import elevate, store

__all__ = ["apply_op", "LEGACY_DISABLE"]

# 隐藏标记的缺省值名——Windows 用它在 shell 项上标记「已禁用」（scan 也认它）。
LEGACY_DISABLE = "LegacyDisable"

_ACTIONS = ("disable", "restore", "delete")
_HIVES = ("hkcu", "hklm")

_WRITE_FAILED = "写入未生效（可能被安全软件拦截）"
# 提权失败的错误码 → 用户可读文案。cancelled 是「用户在 UAC 点了否」，不是故障，文案
# 必须说清「未做任何修改」，否则用户会以为半途改了东西而手动去收拾残局。
# write_failed 是子进程里的回读校验失败，与直写路径共用同一句文案：现象同源（写没
# 落地），用户要的不是「哪条链路失败」而是「去查安全软件」。
_ERROR_TEXTS = {
    "cancelled": "已取消（UAC 被拒绝），未做任何修改",
    "timeout": "未收到提权结果，请稍后重试",
    "write_failed": _WRITE_FAILED,
}
_JOB_FAILED = "提权作业失败"


def _result(ok, detail):
    """统一返回形状（只有 ok/detail 两个键——调用方只认这两个）。"""
    return {"ok": bool(ok), "detail": str(detail)}


def _marker(name):
    """隐藏标记的值名：`name` 为 None/空 → `LegacyDisable`。"""
    return str(name) if name else LEGACY_DISABLE


# ── 参数校验（任何写之前全部判完，非法 op 一步都不许走）──────────────────
def _reject(op):
    """非法 op → 失败结果 dict；合法返回 None。

    校验顺序即「越便宜的越先」：未知 action → hive → key_path → delete 的两条删除禁令。
    删除禁令排在最后是因为它们要同时看 action 与 hive，先把 action 剔掉才不会给
    `{"action":"disable","builtin":true}` 报一句风马牛不相及的「系统内建项不可删除」。
    """
    if not isinstance(op, dict):
        return _result(False, "操作参数非法")
    action = str(op.get("action") or "")
    hive = str(op.get("hive") or "").strip().lower()
    key_path = str(op.get("key_path") or "").strip()
    if action not in _ACTIONS:
        return _result(False, "不支持的操作")
    if hive not in _HIVES:
        return _result(False, f"不支持的 hive: {hive or '(空)'}")
    if not key_path:
        return _result(False, "缺少 key_path")
    if action == "delete":
        if hive != "hkcu":
            return _result(False, "HKLM 项仅支持隐藏")
        if op.get("builtin"):
            return _result(False, "系统内建项不可删除")
    return None


# ── hkcu 直写路径（写后回读校验在本层做）───────────────────────────────
def _run_direct(backend, action, key_path, name, original):
    """直写 + 回读；→ 失败结果 dict，成功 None。"""
    marker = _marker(name)
    try:
        if action == "disable":
            backend.set("hkcu", key_path, marker, "")
            return None if backend.get("hkcu", key_path, marker) is not None else _failed()
        if action == "restore":
            backend.delete("hkcu", key_path, marker)
            if original is not None:              # 删掉标记，再把隐藏前的原值写回去
                backend.set("hkcu", key_path, marker, original)
            current = backend.get("hkcu", key_path, marker)
            # 回读口径：标记值必须消失（original 为 None 时就是 None）；原值被还原回来
            # 的场景读到的是原值，同样算落地成功。
            if current is None or (original is not None and current == str(original)):
                return None
            return _failed()
        backend.delete_tree("hkcu", key_path)
        return None if backend.list_keys("hkcu", key_path) == [] else _failed()
    except Exception:            # 契约外的后端也不把异常抛给 GUI 线程
        return _failed()


def _failed():
    return _result(False, _WRITE_FAILED)


# ── hklm 提权路径（回读在子进程 exec_ops 里，这里只映射错误码）────────────
def _job_ops(action, hive, key_path, name, original):
    """动作 → 提权作业原语列表。

    delete 走不到这里（`_reject` 已限定 delete 只走 hkcu），故此处只处理 disable/restore。
    """
    marker = _marker(name)
    if action == "disable":
        return [elevate.set_op(hive, key_path, marker, "")]
    steps = [elevate.delete_op(hive, key_path, marker)]
    if original is not None:      # 顺序：先删标记再回填原值（与直写路径同一条不变量）
        steps.append(elevate.set_op(hive, key_path, marker, original))
    return steps


def _run_elevated(action, hive, key_path, name, original):
    """写作业 → 提权执行；→ 失败结果 dict，成功 None。

    父进程绝不直写 HKLM：无权限的写入是静默的，直写既改不动又会把「已隐藏」报给用户。
    """
    job = {"ops": _job_ops(action, hive, key_path, name, original)}
    try:
        result = elevate.run_job(job)
    except Exception:
        return _result(False, _JOB_FAILED)
    if isinstance(result, dict) and result.get("ok"):
        return None
    error = result.get("error") if isinstance(result, dict) else None
    return _result(False, _ERROR_TEXTS.get(error, _JOB_FAILED))


# ── 对外入口 ────────────────────────────────────────────────────────────
def apply_op(backend, op, *, store_mod=None):
    """执行一个隐藏/还原/删除动作 → `{"ok": bool, "detail": str}`。

    顺序是硬约定，任何一步都不能换：**校验 → 备份 → 写 → 回读 → 记账本**。
    备份在写之前（账本出错才有可回滚的快照），账本在回读之后（写没落地就记账本，
    账本就记下了一次从未发生的改动）。

    `store_mod` 用于注入账本模块（默认本包的 `store`）；测试可以整体替换掉它。
    父进程直写与提权两条路径都在这里收口，所以「hkcu 直写、hklm 走作业」这条规则
    只写了一遍。
    """
    bad = _reject(op)
    if bad is not None:
        return bad
    action = str(op.get("action") or "")
    hive = str(op.get("hive") or "").strip().lower()
    key_path = str(op.get("key_path") or "").strip()
    name, original = op.get("name"), op.get("original")
    ledger = store_mod or store

    ledger.backup_snapshot(f"{action} {key_path}")
    failure = (_run_elevated(action, hive, key_path, name, original) if hive == "hklm"
               else _run_direct(backend, action, key_path, name, original))
    if failure is not None:
        return failure

    if action == "disable":
        ledger.add_disabled(hive, key_path, name, original)
    else:                       # restore 与 delete 同样按 (hive, key_path, name) 销账
        ledger.remove_disabled(hive, key_path, name)
    return _result(True, f"已完成: {action} {key_path}")