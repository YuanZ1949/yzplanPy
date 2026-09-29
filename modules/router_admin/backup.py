"""router_admin/backup：改配置前把远端 /etc/config 备份到本地。

远端先 `cp` 到 /tmp 再取回文本（一次 batch 即可），本地落到
<DATA_DIR>/router_admin/backups/，保留最近 MAX_BACKUPS 份。

本地备份是**读操作**——即使路由器已失联，也能据此手工恢复。
所有路径操作都做目录内校验，杜绝路径穿越。
"""
import os
import re
import time

from core.constants import DATA_DIR

from .connection import is_allowed_config

BACKUP_DIR = os.path.join(DATA_DIR, "router_admin", "backups")
MAX_BACKUPS = 20

REMOTE_TMP_DIR = "/tmp"
_STAMP_RE = re.compile(r"^\d{8}_\d{6}_[A-Za-z0-9_.-]+$")


class BackupError(ValueError):
    """备份参数非法。"""


def _remote_tmp(section):
    if not is_allowed_config(section):
        raise BackupError(f"{section!r} 不在白名单内")
    return f"{REMOTE_TMP_DIR}/yzp_bk_{section}"


def build_remote_backup_command(section):
    """远端备份：cp 到 /tmp 并确认。"""
    tmp = _remote_tmp(section)
    return (f"cp /etc/config/{section} {tmp} 2>/dev/null && "
            f"wc -c < {tmp} | tr -d ' '")


def build_remote_read_command(section):
    """取回远端备份内容。"""
    return f"cat {_remote_tmp(section)} 2>/dev/null"


def build_remote_cleanup_command(section):
    """清理远端临时备份。"""
    return f"rm -f {_remote_tmp(section)}"


def _filename(section, timestamp=None):
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(timestamp or time.time()))
    return f"{stamp}_{section}"


def save_backup(section, content, *, timestamp=None):
    """把配置内容存到本地。返回文件绝对路径；失败返回 None。"""
    if not is_allowed_config(section):
        raise BackupError(f"{section!r} 不在白名单内")
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, _filename(section, timestamp))
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(str(content or ""))
    except (OSError, ValueError):
        return None
    prune()
    return path


def _inside_backup_dir(path):
    """路径必须落在 BACKUP_DIR 内且是普通文件。"""
    if not path:
        return False
    try:
        root = os.path.abspath(BACKUP_DIR)
        target = os.path.abspath(path)
    except (OSError, ValueError):
        return False
    return os.path.commonpath([root, target]) == root and os.path.isfile(target)


def read_backup(path):
    """读备份内容；路径非法或不存在返回 None。"""
    if not _inside_backup_dir(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, ValueError):
        return None


def delete_backup(path):
    """删除备份。返回 True/False。"""
    if not _inside_backup_dir(path):
        return False
    try:
        os.remove(path)
    except OSError:
        return False
    return True


def _split_name(name):
    """`20260929_103000_network` -> ("20260929_103000", "network")。"""
    parts = name.split("_", 2)
    stamp = parts[0] if parts else ""
    section = parts[2] if len(parts) > 2 else ""
    return stamp, section


def _format_stamp(stamp):
    """`20260929_103000` -> `2026-09-29 10:30:00`；格式不符则原样返回。"""
    if len(stamp) != 15 or stamp[8] != "_":
        return stamp
    return (f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]} "
            f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}")


def list_backups():
    """列出备份，按时间倒序（新→旧）。[{path,name,section,ts,size}]"""
    out = []
    try:
        names = os.listdir(BACKUP_DIR)
    except (OSError, ValueError):
        return out
    for name in names:
        if not _STAMP_RE.match(name):
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        stamp, section = _split_name(name)
        out.append({
            "path": path,
            "name": name,
            "section": section,
            "ts": _format_stamp(stamp),
            "size": size,
        })
    out.sort(key=lambda item: item["name"], reverse=True)
    return out


def prune():
    """裁剪到最近 MAX_BACKUPS 份，返回删除数量。"""
    items = list_backups()
    removed = 0
    for item in items[MAX_BACKUPS:]:
        if delete_backup(item["path"]):
            removed += 1
    return removed


def format_size(size):
    """字节数格式化。"""
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB"):
        if value < 1024 or unit == "MB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} MB"
