"""right_menu 账本 store：禁用账 / ShellNew 隐藏 / 自定义项 / yzmenu / 还原点。

纯 JSON 单文件账本 `<DATA_DIR>/right_menu/state.json`（data/ 下，已 gitignore）。Qt-free
操作层的最底层：`--elevated-job` 提权作业通道会在一切 Qt import 之前调用，绝不 import Qt。
三条不变量：

  * **调用时读全局**：`STATE_PATH`/`BACKUP_DIR`/`TEMPLATES_DIR`/`MAX_BACKUPS` 一律在
    函数体内读，绝不缓存——测试与 conftest 的 `_isolate_db` 靠 monkeypatch 拦截。
  * **原子写**：先写 `.tmp` 再 `os.replace`，崩溃只留可识别的 .tmp，账本正文永远完整
    （截断的代价是禁用记录全丢，用户说不清哪些 right-menu 还能安全还原）。
  * **永不抛异常**：磁盘满/只读/JSON 损坏一律降级（save→False、load→空账本、
    backup_snapshot→None），调用方与 UI 不必 try/except。
"""
import contextlib, json, os, re, time, uuid

from core.constants import DATA_DIR

__all__ = [
    "SCHEMA", "MAX_BACKUPS", "MAX_RESTORE_POINTS", "STATE_PATH", "BACKUP_DIR",
    "TEMPLATES_DIR", "load", "save", "backup_snapshot", "add_disabled",
    "remove_disabled", "add_shellnew_hidden", "remove_shellnew_hidden",
    "get_custom_items", "set_custom_items", "set_yzmenu", "add_restore_point",
]

SCHEMA = 1
MAX_BACKUPS = 30
MAX_RESTORE_POINTS = 200   # 还原点只增不减，不设上限会随使用无限膨胀

_RM_DIR = os.path.join(DATA_DIR, "right_menu")
STATE_PATH = os.path.join(_RM_DIR, "state.json")
BACKUP_DIR = os.path.join(_RM_DIR, "backups")
TEMPLATES_DIR = os.path.join(_RM_DIR, "templates")

_LIST_KEYS = ("disabled", "shellnew_hidden", "custom_items", "restore_points")
# 每个账桶的键名形状 (路径键, 值名键, 是否带 original)，对齐 spec 5.8：
_KEYS = {"disabled": ("key_path", "name", True),        # design.md:266
         "shellnew_hidden": ("path", "orig_name", False)}   # design.md:267


# ── 骨架与归一化 ──────────────────────────────────────────────────────
def _empty_state():
    """空账本骨架（schema 恒为 SCHEMA）。每次调用返回全新对象。"""
    return {"schema": SCHEMA, "disabled": [], "shellnew_hidden": [], "custom_items": [],
            "restore_points": [], "yzmenu": {"installed": False, "actions": []}}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _identity(hive, key_path, name):
    """账本条目的唯一标识 `(hive, key_path, name)`，用于去重与删除。

    hive 大小写不敏感（注册表键名本就不敏感）；值名 None 即默认值，与
    registry_backend._name 同约定。
    """
    return (str(hive or "").strip().upper(),
            str(key_path or "").strip().strip("\\"),
            "" if name is None else str(name))


def _match(item, ident, keys):
    """条目是否命中标识（容忍历史条目缺字段/非字典）。"""
    if not isinstance(item, dict):
        return False
    return _identity(item.get("hive"), item.get(keys[0]),
                     item.get(keys[1])) == ident


# ── 读 / 写 ───────────────────────────────────────────────────────────
def load():
    """读账本。文件缺失/损坏/字段形状不对，一律降级为「补齐后的空账本」。

    逐字段校正而非整份信任：早期版本写出的文件或手工编辑过的文件可能缺键、
    类型不对，下游直接 `.get()` 取用会在真值上炸掉。yzmenu 形状升级不做迁移：
    旧的 enabled/entries 会被读成「未安装」（本模块尚未上线，无存量账本可丢）。
    """
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return _empty_state()
    if not isinstance(raw, dict):
        return _empty_state()
    state = _empty_state()
    for key in _LIST_KEYS:
        if isinstance(raw.get(key), list):
            state[key] = raw[key]
    yzmenu = raw.get("yzmenu")
    if isinstance(yzmenu, dict):
        actions = yzmenu.get("actions")
        state["yzmenu"] = {"installed": bool(yzmenu.get("installed")),
                           "actions": actions if isinstance(actions, list) else []}
    return state


def save(state):
    """原子写账本。成功 True；磁盘满/只读/值不可序列化等任何失败 False。

    TypeError 一并吞（同属「降级不抛」）。"""
    path = STATE_PATH                  # 调用时读全局，勿缓存
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())  # 先把正文刷到盘，再 rename
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        # 半文件不留残留（下次 save 会覆盖）；删不掉也不算失败
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return False
    return True


# ── 备份快照 ──────────────────────────────────────────────────────────
def _snapshot_name(reason):
    """`20261005_141530_disable_hkcu.json`；同秒同名加 `_1`/`_2` 序号。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"\W+", "_", str(reason or "snapshot"))[:40] or "snapshot"
    base = f"{stamp}_{slug}"
    path = os.path.join(BACKUP_DIR, base + ".json")
    seq = 1
    while os.path.exists(path):
        path = os.path.join(BACKUP_DIR, f"{base}_{seq}.json")
        seq += 1
    return path


def _prune_backups():
    """按 mtime 保留最新 MAX_BACKUPS 份，返回删除数量。"""
    try:
        names = os.listdir(BACKUP_DIR)
    except (OSError, ValueError):
        return 0
    items = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            items.append((os.path.getmtime(path), name, path))
        except OSError:
            continue
    items.sort(key=lambda item: (item[0], item[1]), reverse=True)   # 新→旧
    removed = 0
    for _, _, path in items[MAX_BACKUPS:]:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


def backup_snapshot(reason):
    """把当前账本快照写进 BACKUP_DIR，返回文件路径；失败返回 None。

    快照源是 `load()` 的内存结果而非 copy 文件：首次操作前磁盘上可能根本没有
    state.json；且 copy 会把被截断的半写文件也拷成「备份」，正是 router_admin
    backup 事故（备份里没有可回滚内容 → 安全网失效）的同款陷阱。"""
    state = load()
    path = _snapshot_name(reason)
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
    except (OSError, ValueError, TypeError):
        return None
    _prune_backups()
    return path


# ── 变更助手（统一 load → 改 → save）────────────────────────────────────
def _upsert(bucket, hive, path, name, original=None):
    """按标识去重后追加一条账（重复禁用同一项只保留最新原值）。"""
    state = load()
    ident = _identity(hive, path, name)
    keys = _KEYS[bucket]
    kept = [item for item in state[bucket] if not _match(item, ident, keys)]
    entry = {"hive": ident[0], keys[0]: ident[1], keys[1]: ident[2]}
    if keys[2]:                       # 只有 disabled 账带 original（spec:266）
        entry["original"] = original
    entry["ts"] = _now()
    state[bucket] = kept + [entry]
    return save(state)


def _drop(bucket, hive, path, name=None):
    """按标识移除一条账；账不存在也照常落一次盘（保持调用方语义统一）。"""
    state = load()
    ident = _identity(hive, path, name)
    state[bucket] = [item for item in state[bucket]
                     if not _match(item, ident, _KEYS[bucket])]
    return save(state)


def add_disabled(hive, key_path, name, original=None):
    """记一条「已禁用」账；`original` 存禁用前的原值，供后续还原。"""
    return _upsert("disabled", hive, key_path, name, original)


def remove_disabled(hive, key_path, name=None):
    """移除「已禁用」账（disable 与 restore 共用同一标识）。"""
    return _drop("disabled", hive, key_path, name)


def add_shellnew_hidden(hive, path, orig_name):
    """记一条「ShellNew 已隐藏」账（spec:267 形状，无 original 键）。

    不带 original 是因为隐藏只给值名加后缀，原值名本身就是还原数据。
    """
    return _upsert("shellnew_hidden", hive, path, orig_name)


def remove_shellnew_hidden(hive, path, orig_name=None):
    """移除「ShellNew 已隐藏」账（与 add 用同一标识匹配）。"""
    return _drop("shellnew_hidden", hive, path, orig_name)


def get_custom_items():
    """自定义菜单项列表（磁盘状态的副本，改动它不会回写）。"""
    return list(load()["custom_items"])


def set_custom_items(items):
    """整体覆盖自定义菜单项；非字典条目直接丢弃。"""
    state = load()
    state["custom_items"] = [item for item in (items or []) if isinstance(item, dict)]
    return save(state)


def set_yzmenu(installed, actions):
    """覆盖写入 yzmenu 开关（installed）与动作列表（actions）。"""
    state = load()
    state["yzmenu"] = {"installed": bool(installed),
                       "actions": [str(item) for item in (actions or [])]}
    return save(state)


def add_restore_point(reason, changes=None):
    """追加还原点（spec design.md:270 的 id/reason/changes/ts），丢最旧的。"""
    state = load()
    points = list(state["restore_points"])
    points.append({"id": uuid.uuid4().hex, "reason": str(reason or ""),
                   "changes": changes, "ts": _now()})
    state["restore_points"] = points[-MAX_RESTORE_POINTS:]
    return save(state)