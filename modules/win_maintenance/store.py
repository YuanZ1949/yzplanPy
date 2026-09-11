"""win_maintenance 数据层：只读 Windows 事件日志（无 GUI 依赖）。

所有函数在事件日志不可用/无权限/读取失败时返回空结果，绝不抛异常。
win32evtlog 为惰性导入：未安装 pywin32 时功能自动降级为空数据。
"""
import datetime

_LOG_TYPES = ("System", "Application", "Security")

# win32evtlog 事件类型常量（与 EVENTLOG_*_TYPE 一致）
LEVEL_ERROR = 0x1
LEVEL_WARNING = 0x2
LEVEL_INFO = 0x4
LEVEL_SUCCESS = 0x8
LEVEL_FAILURE = 0x10

_LEVEL_NAMES = {
    LEVEL_ERROR: "错误",
    LEVEL_WARNING: "警告",
    LEVEL_INFO: "信息",
    LEVEL_SUCCESS: "成功",
    LEVEL_FAILURE: "失败",
}

# get_log_stats 统计最近 24 小时
_STATS_HOURS = 24
# 统计/读取的硬上限，避免超大日志拖垮 UI
_MAX_STATS_RECORDS = 50000


def _import_evtlog():
    try:
        import win32evtlog
        return win32evtlog
    except ImportError:
        return None


def _ts_to_str(ts):
    """TimeGenerated 兼容 pywintypes.datetime 与 epoch 秒两种形态。"""
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            return ""
    try:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except AttributeError:
        return str(ts)


def _ts_to_dt(ts):
    """把记录时间转为 datetime（失败返回 None）。"""
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        return ts.replace(tzinfo=None)
    except AttributeError:
        return None


def _level_name(etype):
    return _LEVEL_NAMES.get(int(etype), f"类型{int(etype)}")


def _format_message(handle, record):
    """格式化事件消息：优先 SafeFormatMessage，失败回退 StringInserts。"""
    try:
        import win32evtlogutil
        msg = win32evtlogutil.SafeFormatMessage(record, handle)
        if msg and str(msg).strip():
            return str(msg).strip()
    except Exception:
        pass
    inserts = getattr(record, "StringInserts", None) or []
    return " | ".join(str(i) for i in inserts if str(i).strip())


def _matches(rec, level, keyword, date_from):
    """客户端过滤：级别 / 关键词 / 时间下限。"""
    if level is not None:
        etype = int(rec.EventType)
        if isinstance(level, (list, tuple, set)):
            if etype not in level:
                return False
        elif etype != level:
            return False
    if date_from is not None:
        rec_dt = _ts_to_dt(rec.TimeGenerated)
        if rec_dt is not None and rec_dt < date_from:
            return False
    if keyword:
        kw = str(keyword).strip().lower()
        if kw:
            source = str(getattr(rec, "SourceName", "") or "").lower()
            msg = str(getattr(rec, "StringInserts", None) or "").lower()
            if kw not in source and kw not in msg:
                return False
    return True


def read_event_log(log_type="System", level=None, keyword=None,
                   date_from=None, limit=200):
    """读取事件日志，返回 list[dict]。

    每个 dict 含 time/source/level/event_id/message（level 为中文名）。
    任何失败（日志不可用/无权限/参数非法）返回 []，绝不抛异常。
    """
    evtlog = _import_evtlog()
    if evtlog is None or log_type not in _LOG_TYPES:
        return []
    if isinstance(date_from, str):
        try:
            date_from = datetime.datetime.fromisoformat(date_from)
        except ValueError:
            date_from = None
    handle = None
    try:
        handle = evtlog.OpenEventLog(None, log_type)
        flags = evtlog.EVENTLOG_BACKWARDS_READ | evtlog.EVENTLOG_SEQUENTIAL_READ
        records = []
        while len(records) < limit:
            batch = evtlog.ReadEventLog(handle, flags, 0, limit - len(records))
            if not batch:
                break
            records.extend(batch)
        out = []
        for rec in records:
            if not _matches(rec, level, keyword, date_from):
                continue
            out.append({
                "time": _ts_to_str(rec.TimeGenerated),
                "source": str(getattr(rec, "SourceName", "") or ""),
                "level": _level_name(getattr(rec, "EventType", 0)),
                "event_id": int(getattr(rec, "EventID", 0)),
                "message": _format_message(handle, rec),
            })
        return out
    except Exception:
        return []
    finally:
        if handle is not None:
            try:
                evtlog.CloseEventLog(handle)
            except Exception:
                pass


def get_log_stats(log_type="System"):
    """统计最近 24 小时各级别事件数量，返回 dict[str, int]。

    键为中文级别名（错误/警告/信息/成功/失败），失败时全 0。
    """
    evtlog = _import_evtlog()
    stats = {name: 0 for name in _LEVEL_NAMES.values()}
    if evtlog is None or log_type not in _LOG_TYPES:
        return stats
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=_STATS_HOURS)
    handle = None
    try:
        handle = evtlog.OpenEventLog(None, log_type)
        flags = evtlog.EVENTLOG_BACKWARDS_READ | evtlog.EVENTLOG_SEQUENTIAL_READ
        total = 0
        while total < _MAX_STATS_RECORDS:
            batch = evtlog.ReadEventLog(handle, flags, 0, 1024)
            if not batch:
                break
            for rec in batch:
                rec_dt = _ts_to_dt(rec.TimeGenerated)
                if rec_dt is not None and rec_dt < cutoff:
                    return stats  # 已越过 24h 边界，后续更旧，直接结束
                name = _LEVEL_NAMES.get(int(rec.EventType))
                if name is not None:
                    stats[name] += 1
                total += 1
        return stats
    except Exception:
        return stats
    finally:
        if handle is not None:
            try:
                evtlog.CloseEventLog(handle)
            except Exception:
                pass