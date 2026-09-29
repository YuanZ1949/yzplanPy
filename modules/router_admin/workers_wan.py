"""router_admin.workers_wan：宽带账号 Tab 的后台任务（命令一律由 wan.py 构造）。

与 `workers.py` 拆成两个文件的原因：`workers.py` 已被配置/服务两个 Tab 占满，
再加宽带的四个任务会顶破 250 行（AGENTS.md 规则 6）。这里只放任务函数，线程层
（`RouterTask` / `TaskGroup`）与命令构造都不重复实现。

四条任务的失败一律**就地返回 `ok=False` + `stage` + `error`**，不抛异常：这些是
「参数不对 / 没变化 / 读不到配置」这类用户可自己纠正的情况，抛到 `describe_error`
只会变成一句干巴巴的「未预期的错误」。
"""
from . import config_editor, wan
from .workers import backup_then_write


def wan_status_worker(iface=wan.DEFAULT_IFACE):
    """读宽带在线状态。解析失败不抛，原因放 `status.error`。"""

    def worker(session):
        return {"iface": iface, "status": wan.parse_status(
            session.run(wan.build_status_command(iface)))}

    return worker


def wan_account_worker():
    """读回当前宽带账号。**只回 `has_password` 布尔，不回明文口令。**"""

    def worker(session):
        text = session.run(config_editor.build_read_command("network"))
        account = wan.parse_account(config_editor.parse_uci(text))
        account["text_len"] = len(text or "")
        return account

    return worker


def wan_save_worker(username, password=None):
    """读回 network 配置 → 只改账号/口令 → 备份 → 原子写 → 回读校验。

    `password=None` 表示不修改口令。三种提前返回都不写路由器：读取为空、
    字段校验不通过、改动与现值完全一致。
    """

    def worker(session):
        original = session.run(config_editor.build_read_command("network"))
        if not (original or "").strip():
            return {"ok": False, "stage": "read",
                    "error": "读取 /etc/config/network 为空，已中止写入"}
        before = config_editor.parse_uci(original)
        try:
            after = wan.apply_account(before, username=username,
                                      password=password)
        except wan.WanError as exc:
            return {"ok": False, "stage": "validate", "error": str(exc)}
        # 比**解析后的结构**而不是文本：`serialize_uci(parse_uci(x))` 未必与 x
        # 逐字相同（注释会被丢弃、键序被重排），按文本比会永远判不出「无变化」，
        # 于是每次都白备份白写一遍 `/etc/config/network`。
        if after == before:
            return {"ok": False, "stage": "noop", "error": "账号与口令均无变化"}
        got = backup_then_write(session, "network",
                                config_editor.serialize_uci(after))
        got["password_changed"] = password is not None
        return got

    return worker


def wan_redial_worker(iface=wan.DEFAULT_IFACE):
    """下发重拨并回读当时的日志。

    `wan.build_redial_command` 是**分离执行**的（`&` 放到后台），所以本条命令
    立即返回；`sent` 只代表「命令已送达路由器」，**不代表拨号成功**——拨号结果
    要由 UI 按 `wan.REDIAL_POLL_TIMES` 轮询 `wan_status_worker` 来确认。
    """

    def worker(session):
        out = session.run(wan.build_redial_command(iface))
        return {"iface": iface, "sent": wan.REDIAL_MARKER in (out or ""),
                "log": wan.parse_redial_log(
                    session.run(wan.build_redial_read_command()))}

    return worker


def wan_log_worker():
    """读回 `ifdown`/`ifup` 的拨号日志（重拨是分离执行的，此刻可能还在写）。

    只读不删：日志留着才好排查「为什么拨不上」。下一次重拨时同一路径会被 `>`
    覆盖，不需要单独的清理步骤。
    """

    def worker(session):
        raw = session.run(wan.build_redial_read_command())
        return {"raw": (raw or "").strip(), **wan.parse_redial_log(raw)}

    return worker
