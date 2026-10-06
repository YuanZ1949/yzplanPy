"""right_menu 账本 store：禁用账 / ShellNew 隐藏 / 自定义项 / yzmenu / 还原点。

纯 JSON 单文件账本 `<DATA_DIR>/right_menu/state.json`（data/ 下，已 gitignore）。Qt-free
操作层的最底层：`--elevated-job` 提权作业通道会在一切 Qt import 之前调用，绝不 import Qt。
三条不变量：**调用时读全局**（路径/上限函数体内读，测试靠 monkeypatch 拦截）；**原子写**（先写
.tmp 再 os.replace，崩溃只留半文件）；**永不抛异常**（磁盘满/只读/JSON 损坏/非法入参降级为 save→False、load→空账本、backup_snapshot→None）。
"""
import contextlib, json, os, re, time, uuid

from core.constants import DATA_DIR

__all__ = [
    "SCHEMA", "MAX_BACKUPS", "MAX_RESTORE_POINTS", "STATE_PATH", "BACKUP_DIR", "TEMPLATES_DIR",
    "load", "save", "backup_snapshot", "add_disabled", "remove_disabled", "add_shellnew_hidden",
    "remove_shellnew_hidden", "get_custom_items", "set_custom_items", "set_yzmenu",
    "add_restore_point", "restore_all",
]

SCHEMA = 1
MAX_BACKUPS = 30
MAX_RESTORE_POINTS = 200   # 还原点只增不减，不设上限会随使用无限膨胀

_RM_DIR = os.path.join(DATA_DIR, "right_menu")
STATE_PATH = os.path.join(_RM_DIR, "state.json")
BACKUP_DIR = os.path.join(_RM_DIR, "backups")
TEMPLATES_DIR = os.path.join(_RM_DIR, "templates")

_LIST_KEYS = ("disabled", "shellnew_hidden", "custom_items", "restore_points")
# 账桶的键名形状 (路径键, 值名键, 是否带 original)，对齐 spec 5.8；未登记的桶 → _upsert/_drop 拒绝写入：
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
    """账本条目标识：hive 大小写不敏感，值名 None 即默认值（同 registry_backend）。"""
    return (str(hive or "").strip().upper(), str(key_path or "").strip().strip("\\"),
            "" if name is None else str(name))


def _match(item, ident, keys):
    """条目是否命中标识（容忍历史条目缺字段/非字典）。"""
    if not isinstance(item, dict):
        return False
    return _identity(item.get("hive"), item.get(keys[0]), item.get(keys[1])) == ident


# ── 读 / 写 ───────────────────────────────────────────────────────────
def _read_state():
    """→ (状态, state)：'missing' 无文件 / 'corrupt' 存在却读不出 / 'ok' 成功；state 已逐字段校正补齐（绝不整份
    信任 raw）。yzmenu 形状升级不迁移：旧 enabled/entries 读成「未安装」（未上线）。"""
    if not os.path.exists(STATE_PATH):
        return "missing", _empty_state()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        ok = isinstance(raw, dict)
    except (OSError, ValueError):
        ok = False
    if not ok:
        return "corrupt", _empty_state()
    state = _empty_state()
    for key in _LIST_KEYS:
        if isinstance(raw.get(key), list):
            state[key] = raw[key]
    yzmenu = raw.get("yzmenu")
    if isinstance(yzmenu, dict):
        actions = yzmenu.get("actions")
        state["yzmenu"] = {"installed": bool(yzmenu.get("installed")),
                           "actions": actions if isinstance(actions, list) else []}
    return "ok", state


def load():
    """读账本；缺失/损坏/形状不对一律降级为补齐后的空账本（规则见 _read_state）。"""
    return _read_state()[1]


def save(state):
    """原子写账本：先写 `.tmp` 再 `os.replace`。成功 True，任何失败 False。"""
    path = STATE_PATH                  # 调用时读全局，勿缓存
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())  # 先把正文刷到盘，再 rename
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):   # json.dump 遇不可序列化值抛 TypeError
        with contextlib.suppress(OSError):    # 半文件不留残留（删不掉也不算失败）
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
    """按 mtime + 尾部序号保留最新 MAX_BACKUPS 份，返回删除数量。"""
    try:
        names = os.listdir(BACKUP_DIR)
    except (OSError, ValueError):
        return 0
    items = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(BACKUP_DIR, name)
        tail = name[:-len(".json")].rsplit("_", 1)[-1]   # 尾部序号，无后缀 0；数值感知（否则 _op_9 排在 _op_11 前）
        try:
            items.append((os.path.getmtime(path), int(tail) if tail.isdigit() else 0, path))
        except OSError:
            continue
    items.sort(key=lambda item: item[:2], reverse=True)     # 新→旧
    removed = 0
    for _, _, path in items[MAX_BACKUPS:]:
        with contextlib.suppress(OSError):
            os.remove(path)
            removed += 1
    return removed


def backup_snapshot(reason):
    """把当前账本快照写进 BACKUP_DIR，返回路径；失败或账本损坏返回 None。

    快照源是内存账本而非 copy 文件（copy 会把半写的坏文件也拷成「备份」，router_admin
    backup 事故的同款陷阱）；账本读不出时不写——空快照「看起来合法」却无内容可还原。"""
    status, state = _read_state()
    if status == "corrupt":            # 不写「合法但空」的误导性快照
        return None
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
    keys = _KEYS.get(bucket)
    if not keys:
        return False
    state = load()
    ident = _identity(hive, path, name)
    kept = [item for item in state[bucket] if not _match(item, ident, keys)]
    entry = {"hive": ident[0], keys[0]: ident[1], keys[1]: ident[2]}
    if keys[2]:                       # 只有 disabled 账带 original（spec:266）
        entry["original"] = original
    entry["ts"] = _now()
    state[bucket] = kept + [entry]
    return save(state)


def _drop(bucket, hive, path, name=None):
    """按标识移除一条账；账不存在也照常落一次盘（保持调用方语义统一）。"""
    keys = _KEYS.get(bucket)
    if not keys:
        return False
    state = load()
    ident = _identity(hive, path, name)
    state[bucket] = [i for i in state[bucket] if not _match(i, ident, keys)]
    return save(state)


def add_disabled(hive, key_path, name, original=None):
    """记一条「已禁用」账；`original` 存禁用前的原值，供后续还原。"""
    return _upsert("disabled", hive, key_path, name, original)


def remove_disabled(hive, key_path, name=None):
    """移除「已禁用」账（disable 与 restore 共用同一标识）。"""
    return _drop("disabled", hive, key_path, name)


def add_shellnew_hidden(hive, path, orig_name):
    """记一条「ShellNew 已隐藏」账（spec:267；无 original 键，原值名即还原数据）。"""
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
    try:
        items = list(items or [])
    except TypeError:                # 非可迭代标量（如 int）当空，绝不抛
        items = []
    state["custom_items"] = [item for item in items if isinstance(item, dict)]
    return save(state)


def set_yzmenu(installed, actions):
    """覆盖写入 yzmenu 开关（installed）与动作列表（actions）。"""
    state = load()
    try:
        actions = list(actions or [])
    except TypeError:                # 同上：标量输入不抛
        actions = []
    state["yzmenu"] = {"installed": bool(installed), "actions": [str(i) for i in actions]}
    return save(state)


def add_restore_point(reason, changes=None):
    """追加还原点（spec design.md:270 的 id/reason/changes/ts），丢最旧的。"""
    state = load()
    points = state["restore_points"]
    points.append({"id": uuid.uuid4().hex, "reason": str(reason or ""),
                   "changes": changes, "ts": _now()})
    points[:] = points[-MAX_RESTORE_POINTS:]   # FIFO 丢最旧的
    return save(state)

# restore_all 的实现在 store_restore.py（顶层零 import），故必须放文件末尾再导出
from .store_restore import restore_all  # noqa: E402
