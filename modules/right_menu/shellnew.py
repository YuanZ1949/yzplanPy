"""right_menu ShellNew 新建菜单管理：扫描 / 隐藏 / 恢复 / 新增 / 删除。

Explorer「新建」菜单的内容不在 `shell` 键里，而在每个文件类型键下的
`Software\\Classes\\<ext>\\ShellNew`：`NullFile` = 新建空文件，`FileName` = 拿模板
新建副本。本模块负责这批键的只读枚举与四个写动作。

**为什么隐藏 = 给值名加后缀**：ShellNew 没有官方的「禁用」标志位（不像 shell 项的
`LegacyDisable`），通用手法只有改名——explorer 只认约定值名，改名即等价删除，而改名
能原样改回来，比删键安全。

跨任务契约：**Qt-free**（可能在 `--elevated-job` 早退通道的 import 链上被拉进来）；
**调用时取模块属性**（`from . import elevate, store` 后按 `store.xxx()` 调用——直接
绑定 `run_job` 会把名字在 import 时钉死，monkeypatch 拦不到「UAC 被取消」）；
**永不抛**；**顺序是硬约定**校验 → 备份 → 写 → 回读 → 记账本（写没落地就记账本，账本
就记下了一次从未发生的改动）；**HKLM 只隐藏、只走提权**（直写是静默无效的）。
"""
import os
import re
import uuid

from . import elevate, store

__all__ = ["HIDDEN_SUFFIX", "EXT_RE", "scan_shellnew", "hide_shellnew",
           "restore_shellnew", "create_shellnew", "delete_shellnew"]

# 隐藏标记：拼在值名尾部；explorer 不认它，这项就从「新建」菜单消失，可原样还原。
HIDDEN_SUFFIX = "__yzhidden"
# 扩展名只收「点 + 1~30 个字母数字/下划线/点/连字符」：它直接拼进注册表键路径。
EXT_RE = re.compile(r"^\.[A-Za-z0-9_.-]{1,30}$")

_CLASSES = r"Software\Classes"
_SHELLNEW = "ShellNew"
_SHELLNEW_FOLDED = "shellnew"           # 键名大小写不敏感，比较统一 casefold
_HIVES = ("hkcu", "hklm")
# 标准值名及其顺序（顺序即优先级：kind 与「隐藏哪个值」都按它先来后到）。
_CANON = ("NullFile", "FileName", "Data", "Command")
_CANON_FOLDED = {name.casefold(): name for name in _CANON}
_KIND = {"NullFile": "null", "FileName": "template", "Data": "data", "Command": "command"}
_CREATE_KINDS = ("null", "template")
_FILENAME = "filename"                  # 模板路径所在的值名（带不带后缀都认）

_WRITE_FAILED = "写入未生效（可能被安全软件拦截）"
# 提权失败的错误码 → 用户可读文案（cancelled 是「用户在 UAC 点了否」，不是故障）。
_ERROR_TEXTS = {"cancelled": "已取消（UAC 被拒绝），未做任何修改",
                "timeout": "未收到提权结果，请稍后重试"}
_JOB_FAILED = "提权作业失败"
_BAD_EXT = "扩展名格式无效"
_EXISTS = "已存在同名项"
_HKLM_ONLY_HIDE = "系统项仅支持隐藏"
_BAD_PARAM = "参数非法"


# ── 结果 / 取值助手 ────────────────────────────────────────────────────
def _result(ok, detail):
    """统一返回形状（只有 ok/detail 两个键——调用方只认这两个）。"""
    return {"ok": bool(ok), "detail": str(detail)}


def _failed():
    return _result(False, _WRITE_FAILED)


def _values(backend, hive, key_path):
    """实时读值表 `[(值名, 值)]`；后端异常降级为空表（当作「没值」）。"""
    try:
        return [(str(n), "" if v is None else str(v))
                for n, v in backend.list_values(hive, key_path)]
    except Exception:
        return []


def _hidden_pair(backend, hive, key_path):
    """第一个已隐藏的标准值 `(原名, 值)`；没有返回 None（只认 `_CANON` 里的名字）。"""
    for name, data in _values(backend, hive, key_path):
        orig = name[:-len(HIDDEN_SUFFIX)] if name.endswith(HIDDEN_SUFFIX) else name
        if name != orig and _CANON_FOLDED.get(orig.casefold()):
            return orig, data
    return None


def _first_open(backend, hive, key_path):
    """第一个未隐藏的标准值 `(原名, 值)`（`_CANON` 顺序；非标准名与带后缀名跳过）。"""
    hits = [(_CANON.index(c), name, d) for name, d in _values(backend, hive, key_path)
            for c in [_CANON_FOLDED.get(name.casefold())]
            if c and not name.endswith(HIDDEN_SUFFIX)]
    return min(hits)[1:] if hits else None


def _target(item):
    """item → `(hive, key_path)`；任一为空返回 `(None, None)`（调用方报参数非法）。"""
    item = item if isinstance(item, dict) else {}
    hive = str(item.get("hive") or "").strip().lower()
    key_path = str(item.get("key_path") or "").strip()
    return (hive, key_path) if hive and key_path else (None, None)


# ── 写 + 回读（hkcu 直写与 hklm 提权两条路径在此收口）────────────────────
def _write_rename(backend, hive, key_path, old, new, data):
    """把值 `old` 改名成 `new`（先删旧名再写新名，反了等于没改名）；失败返回失败 dict。"""
    if hive == "hklm":                  # 父进程绝不直写 HKLM：无权限的写入是静默的
        job = {"ops": [elevate.delete_op(hive, key_path, old),
                       elevate.set_op(hive, key_path, new, data)]}
        try:
            out = elevate.run_job(job)
        except Exception:              # 作业通道异常也不拖垮 GUI 线程
            return _result(False, _JOB_FAILED)
        if isinstance(out, dict) and out.get("ok"):
            return None                 # 提权侧的逐条回读在子进程 exec_ops 里做
        error = out.get("error") if isinstance(out, dict) else None
        return _result(False, _ERROR_TEXTS.get(error, _JOB_FAILED))
    try:
        backend.delete(hive, key_path, old)
        backend.set(hive, key_path, new, data)
        # 回读口径：旧名必须消失、新名必须带着原值在。少一条即写没落地（无权限或被
        # 安全软件拦截的写入，与成功在返回值上完全一样）。
        landed = (backend.get(hive, key_path, old) is None
                  and backend.get(hive, key_path, new) == data)
    except Exception:
        return _failed()
    return None if landed else _failed()


# ── 扫描 ────────────────────────────────────────────────────────────────
def scan_shellnew(backend):
    """扫两个 hive 下带 `ShellNew` 子键的扩展名 → item 列表（只读，不写）。"""
    items = []
    for hive in _HIVES:
        for ext in backend.list_keys(hive, _CLASSES):
            # 只收 `.` 开头的扩展名：Software\Classes 下混着 * / Directory 等文件类键
            if not str(ext).startswith("."):
                continue
            ext_key = f"{_CLASSES}\\{ext}"
            if not any(str(sub).casefold() == _SHELLNEW_FOLDED
                       for sub in backend.list_keys(hive, ext_key)):
                continue
            key_path = ext_key + "\\" + _SHELLNEW
            values = _values(backend, hive, key_path)
            # kind 按 _CANON 顺序取第一个标准值名（值名先剥后缀），故隐藏过的项仍报
            # 得出原类型；模板路径带不带后缀都认，隐藏过的模板项也得显示指向哪个文件。
            names = {name.casefold() for name, _ in values}
            kind = next((_KIND[canon] for canon in _CANON
                         if canon.casefold() in names
                         or (canon + HIDDEN_SUFFIX).casefold() in names), "unknown")
            items.append({
                "hive": hive, "ext": ext, "key_path": key_path, "values": values,
                "kind": kind,
                "hidden": any(name.endswith(HIDDEN_SUFFIX) for name, _ in values),
                "template": next((data for name, data in values
                                  if name.casefold() == _FILENAME), None)})
    return items


# ── 隐藏 / 恢复 ─────────────────────────────────────────────────────────
def hide_shellnew(backend, item, *, store_mod=None):
    """把一个 ShellNew 项的标准值改名加后缀 → 「已隐藏」（可原样还原）。"""
    hive, key_path = _target(item)
    if hive is None:
        return _result(False, _BAD_PARAM)
    # 幂等：已带后缀就一个字节都不写。判定看**实时**值表而非 item（UI 列表是快照）。
    if _hidden_pair(backend, hive, key_path) is not None:
        return _result(True, "已隐藏")
    found = _first_open(backend, hive, key_path)
    if found is None:
        return _result(False, "未找到可隐藏的新建项")
    name, data = found
    ledger = store_mod or store
    ledger.backup_snapshot(f"shellnew hide {key_path}")
    failure = _write_rename(backend, hive, key_path, name, name + HIDDEN_SUFFIX, data)
    if failure is not None:
        return failure                # 回读没过 → 账本一个字都不动
    ledger.add_shellnew_hidden(hive, key_path, name)
    return _result(True, "已隐藏")


def restore_shellnew(backend, item, *, store_mod=None):
    """把带后缀的值名改回原名 → 「已恢复」；本来就没隐藏时幂等报成功。"""
    hive, key_path = _target(item)
    if hive is None:
        return _result(False, _BAD_PARAM)
    pair = _hidden_pair(backend, hive, key_path)
    if pair is None:
        return _result(True, "已恢复")
    # 值数据跟着一起搬回去：后缀只是改名，数据没丢，但拿空值覆盖会把空串/默认值清掉。
    name, data = pair
    ledger = store_mod or store
    ledger.backup_snapshot(f"shellnew restore {key_path}")
    failure = _write_rename(backend, hive, key_path, name + HIDDEN_SUFFIX, name, data)
    if failure is not None:
        return failure
    ledger.remove_shellnew_hidden(hive, key_path, name)
    return _result(True, "已恢复")


# ── 新增 / 删除 ─────────────────────────────────────────────────────────
def create_shellnew(backend, ext, *, name, kind, template_path=None, store_mod=None):
    """给某扩展名新建一条 ShellNew：`null`=空文件、`template`=模板文件 → 只写 HKCU。"""
    ext, kind = str(ext or ""), str(kind or "")
    if not EXT_RE.fullmatch(ext):     # fullmatch：$ 会匹配换行前，留 ".xyz\n" 钻进来
        return _result(False, _BAD_EXT)
    if kind not in _CREATE_KINDS:
        return _result(False, "不支持的新建类型")
    ledger = store_mod or store
    target = f"{_CLASSES}\\{ext}\\{_SHELLNEW}"
    if backend.list_values("hkcu", target):
        return _result(False, _EXISTS)  # 不在有效项上叠第二个，否则「删除」会两个一起清
    data, value_name = "", "NullFile"
    if kind == "template":
        if not template_path or not os.path.isfile(template_path):
            return _result(False, "模板文件不存在")
        try:
            os.makedirs(ledger.TEMPLATES_DIR, exist_ok=True)
            # 8 位随机前缀：同名模板互相覆盖会让先建的「新建」项指到别人的内容上。
            # 已知取舍：写失败时这份副本会留在目录里。
            data = os.path.abspath(os.path.join(
                ledger.TEMPLATES_DIR,
                uuid.uuid4().hex[:8] + "_" + os.path.basename(template_path)))
            with open(template_path, "rb") as src, open(data, "wb") as out:
                out.write(src.read())     # 二进制拷贝：换行/编码原样保留
        except OSError:
            return _result(False, "模板文件不存在")
        value_name = "FileName"
    ledger.backup_snapshot(f"shellnew create {ext}")
    try:
        backend.set("hkcu", target, value_name, data)
        landed = backend.get("hkcu", target, value_name) is not None
    except Exception:
        return _failed()
    return _result(True, f"已添加：{name}" if name else "已添加") if landed else _failed()


def delete_shellnew(backend, item, *, store_mod=None):
    """删掉整个 `ShellNew` 键 → 「已删除」；HKLM 拒绝（系统项只支持隐藏）。"""
    hive, key_path = _target(item)
    if hive is None:
        return _result(False, _BAD_PARAM)
    if hive == "hklm":
        return _result(False, _HKLM_ONLY_HIDE)
    ledger = store_mod or store
    ledger.backup_snapshot(f"shellnew delete {key_path}")
    # 回读看**父键**的子键列表：delete_tree 只删 ShellNew 这棵子树，父扩展名键必须留着
    # （它还挂着 shell\open\command 等别的东西）。删除不销账本（键都没了，「一键还
    # 原」按现状自行收敛）。
    parent = key_path.rsplit("\\", 1)[0]
    try:
        backend.delete_tree(hive, key_path)
        subs = backend.list_keys(hive, parent)
        landed = not any(str(sub).casefold() == _SHELLNEW_FOLDED for sub in subs)
    except Exception:
        return _failed()
    return _result(True, "已删除") if landed else _failed()
