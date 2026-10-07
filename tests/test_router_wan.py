"""tests/test_router_wan.py：宽带(PPPoE)账号管理 + 独立重拨 + 状态查询的纯逻辑测试。

真机事实（本文件的断言都据此写，来源见 docs/superpowers/specs）：
- `/etc/config/network` 的 `config interface 'wan'` 段真实字段：
  proto='pppoe' / username='<21 字符>' / password='<8 字符>' /
  ifname='eth0' / mtu='1500' / mru='1480' / ipv6='auto' /
  macaddr='02:00:00:00:00:01' / special='0' / last_succeed='1'
- `ubus call network.interface.wan status` 返回**多行美化 JSON**（约 1757 字符、
  72 行），可整段取回后 `json.loads`；键含 up/pending/available/uptime/proto/
  device/l3_device/ipv4-address/ipv6-address/dns-server
- L3 设备 `l3_device='pppoe-wan'`，物理口 `device='eth0'`
- `/sbin/ifup` 与 `/sbin/ifdown` 均存在，**接受的是 UCI 段名 `wan`**（不是 pppoe-wan）
- 真机有 `wan_check` 守护脚本会自动重拨
- BusyBox tty 单行输入上限约 500 字节，故命令都不能太长
"""
import json
import os
import pathlib

import pytest

from modules.router_admin import config_editor, wan
from modules.router_admin.replay import ReplaySession
from modules.router_admin.wan import WanError

# 真机 /etc/config/network 里 config interface 'wan' 段的等价结构。
# 账号 / 口令 / MAC 一律用虚构值（仓库会推到公开 GitHub/Gitee）；结构与真机一致。
REAL_UCI = {
    "interface": {
        "loopback": {"proto": "static"},
        "wan": {
            "proto": "pppoe",
            "username": "07550000000@example.gd",
            "password": "a1b2c3d4",
            "ifname": "eth0",
            "macaddr": "02:00:00:00:00:01",
            "mtu": "1500",
            "mru": "1480",
            "ipv6": "auto",
            "special": "0",
            "last_succeed": "1",
        },
        "lan": {"proto": "static", "ipaddr": "192.168.2.1", "netmask": "255.255.255.0"},
    }
}

# 真机 ubus 状态（截取自 192.168.2.1，已脱敏；结构与真机一致）
REAL_STATUS = json.dumps({
    "up": True,
    "pending": False,
    "available": True,
    "autostart": True,
    "dynamic": False,
    "uptime": 13327,
    "l3_device": "pppoe-wan",
    "proto": "pppoe",
    "device": "eth0",
    "updated": ["addresses", "routes"],
    "metric": 0,
    "dns_metric": 0,
    "delegation": True,
    "ipv4-address": [{"address": "100.67.227.167", "mask": 32,
                      "ptpaddress": "100.67.227.1"}],
    "ipv6-address": [{"address": "240e:3b0:3498:278f::1", "mask": 128}],
    "route6": [],
    "dns-server": ["202.96.134.33", "202.96.128.86"],
})


# ── 接口名校验（命令注入防线）────────────────────────────────────
class TestValidateIface:
    def test_默认是wan(self):
        assert wan.validate_iface(wan.DEFAULT_IFACE) == "wan"

    def test_合法名字原样返回(self):
        assert wan.validate_iface("wan_6") == "wan_6"

    @pytest.mark.parametrize("bad", [
        "a;reboot", "../../etc/passwd", "a b", "a'b", "a\nb", "", "   ",
        "wan;ifdown", "$(id)", "a|b", "a&b", "a`b", "a$b", None, 123,
    ])
    def test_非法名字一律拒绝(self, bad):
        with pytest.raises(WanError):
            wan.validate_iface(bad)

    def test_首尾空白被裁掉而不是放行(self):
        assert wan.validate_iface("  wan  ") == "wan"

    def test_超长名字拒绝(self):
        with pytest.raises(WanError):
            wan.validate_iface("w" * (wan.MAX_ACCOUNT_LEN + 1))


# ── 账号字段校验 ────────────────────────────────────────────────
class TestValidateAccount:
    def test_真实用户名通过(self):
        assert wan.validate_username("07550000000@example.gd") == "07550000000@example.gd"

    def test_用户名首尾空白被裁(self):
        assert wan.validate_username("  user@1  ") == "user@1"

    def test_用户名含单引号拒绝(self):
        # 单引号会直接破坏 UCI 的 option key 'value' 引号配对
        with pytest.raises(WanError):
            wan.validate_username("it's@1")

    def test_用户名含内部空格拒绝(self):
        with pytest.raises(WanError):
            wan.validate_username("a b@1")

    @pytest.mark.parametrize("bad", ["", "   ", "a\nb", "a\x00b", "a\tb",
                                      "a'b", "x" * (wan.MAX_ACCOUNT_LEN + 1), None])
    def test_非法用户名拒绝(self, bad):
        with pytest.raises(WanError):
            wan.validate_username(bad)

    def test_口令允许空格(self):
        assert wan.validate_password("ab cd12") == "ab cd12"

    def test_口令允许单引号以外的所有可打印字符(self):
        assert wan.validate_password("aA1!@#$%^&*()-_=+[]{};:,.<>?/~`|") == \
            "aA1!@#$%^&*()-_=+[]{};:,.<>?/~`|"

    @pytest.mark.parametrize("bad", ["", "   ", "a\nb", "a\x00b", "a'b", "\r\n"])
    def test_非法口令拒绝(self, bad):
        with pytest.raises(WanError):
            wan.validate_password(bad)

    def test_口令超长拒绝(self):
        with pytest.raises(WanError):
            wan.validate_password("p" * (wan.MAX_ACCOUNT_LEN + 1))


# ── 读取账号 ────────────────────────────────────────────────────
class TestParseAccount:
    def test_真机结构解析正确(self):
        got = wan.parse_account(REAL_UCI)
        assert got["present"] is True
        assert got["proto"] == "pppoe"
        assert got["username"] == "07550000000@example.gd"
        assert got["ifname"] == "eth0"
        assert got["mtu"] == "1500"
        assert got["ipv6"] == "auto"

    def test_只回has_password不回明文口令(self):
        # 安全要求：UI 永远拿不到明文口令，只能知道「有没有设」
        got = wan.parse_account(REAL_UCI)
        assert got["has_password"] is True
        assert "a1b2c3d4" not in json.dumps(got, ensure_ascii=False)
        assert "password" not in got

    def test_没有口令时has_password为假(self):
        uci = {"interface": {"wan": {"proto": "dhcp"}}}
        got = wan.parse_account(uci)
        assert got["has_password"] is False
        assert got["present"] is True

    def test_缺wan段时present为假(self):
        got = wan.parse_account({"interface": {"lan": {"proto": "static"}}})
        assert got["present"] is False
        assert got["username"] is None

    def test_空输入不抛异常(self):
        for bad in (None, {}, {"interface": None}, {"interface": {}}):
            assert wan.parse_account(bad)["present"] is False


# ── 写入账号（只动两个键）──────────────────────────────────────
class TestApplyAccount:
    def test_改用户名只动username(self):
        got = wan.apply_account(REAL_UCI, username="new@1", password=None)
        section = got["interface"]["wan"]
        assert section["username"] == "new@1"
        assert section["password"] == "a1b2c3d4"          # 口令未被碰
        assert section["proto"] == "pppoe"                # 其余键原样保留
        assert section["ifname"] == "eth0"
        assert got["interface"]["lan"]["ipaddr"] == "192.168.2.1"

    def test_传口令才改口令(self):
        got = wan.apply_account(REAL_UCI, username="a@1", password="newpass")
        assert got["interface"]["wan"]["password"] == "newpass"

    def test_口令为None表示不修改(self):
        got = wan.apply_account(REAL_UCI, username="a@1", password=None)
        assert got["interface"]["wan"]["password"] == "a1b2c3d4"

    def test_不修改入参(self):
        before = json.dumps(REAL_UCI, sort_keys=True)
        wan.apply_account(REAL_UCI, username="x@1", password="y")
        assert json.dumps(REAL_UCI, sort_keys=True) == before

    def test_缺wan段时拒绝而不是新建(self):
        # 凭空造 interface 'wan' 段会造出网���上不存在的接口，危险
        with pytest.raises(WanError):
            wan.apply_account({"interface": {"lan": {}}}, username="a@1")

    def test_非法用户名不写(self):
        with pytest.raises(WanError):
            wan.apply_account(REAL_UCI, username="bad'quote")

    def test_非法口令不写(self):
        with pytest.raises(WanError):
            wan.apply_account(REAL_UCI, username="a@1", password="bad'q")

    def test_回写后仍能被parse_uci往返(self):
        from modules.router_admin.config_editor import parse_uci, serialize_uci
        text = serialize_uci(wan.apply_account(REAL_UCI, username="x@1",
                                               password="p@ssw0rd"))
        round_trip = parse_uci(text)["interface"]["wan"]
        assert round_trip["username"] == "x@1"
        assert round_trip["password"] == "p@ssw0rd"
        assert round_trip["proto"] == "pppoe"
        assert round_trip["ifname"] == "eth0"

    def test_含单引号的口令无法安全往返故被拒(self):
        # 单引号会截断 UCI 的 option password '...' 边界，回读必然错值，
        # 所以在**写入前**就必须拒绝，而不是让用户存进去再发现拨不上号
        with pytest.raises(WanError):
            wan.apply_account(REAL_UCI, username="x@1", password="p@ss'w0rd")


# ── 状态命令 ────────────────────────────────────────────────────
class TestStatusCommand:
    def test_默认查wan(self):
        assert wan.build_status_command() == \
            "ubus call network.interface.wan status 2>&1"

    def test_可指定接口(self):
        assert "network.interface.wan_6" in wan.build_status_command("wan_6")

    def test_接口名注入被拒(self):
        with pytest.raises(WanError):
            wan.build_status_command("a; reboot")

    def test_命令不超过真机单行上限(self):
        assert len(wan.build_status_command()) < 500


# ── 状态解析 ────────────────────────────────────────────────────
class TestParseStatus:
    def test_真机状态解析正确(self):
        got = wan.parse_status(REAL_STATUS)
        assert got["up"] is True
        assert got["uptime_s"] == 13327
        assert got["proto"] == "pppoe"
        assert got["device"] == "eth0"
        assert got["l3_device"] == "pppoe-wan"
        assert got["ipv4"] == "100.67.227.167"
        assert got["netmask"] == 32
        assert got["ptp"] == "100.67.227.1"
        assert got["ipv6"] == "240e:3b0:3498:278f::1"
        assert got["dns"] == ["202.96.134.33", "202.96.128.86"]
        assert got["error"] is None

    def test_离线状态也能解析(self):
        got = wan.parse_status(json.dumps({"up": False, "available": True,
                                           "uptime": 0, "proto": "pppoe"}))
        assert got["up"] is False
        assert got["error"] is None
        assert got["ipv4"] is None
        assert got["dns"] == []

    def test_缺少地址字段时为None而非报错(self):
        got = wan.parse_status(json.dumps({"up": True}))
        assert got["ipv4"] is None
        assert got["uptime_s"] is None
        assert got["error"] is None

    def test_非JSON给出错误且不抛(self):
        got = wan.parse_status("ubus: Unknown object 'wan'")
        assert got["up"] is None
        assert got["error"]
        assert "JSON" in got["error"]

    def test_空输出给出错误(self):
        got = wan.parse_status("")
        assert got["up"] is None
        assert got["error"]

    def test_非法JSON不抛(self):
        for bad in (None, "{", "[]", "null", "{'a':1}"):
            assert wan.parse_status(bad)["up"] is None

    def test_成功时也带error键保持形状稳定(self):
        assert "error" in wan.parse_status(REAL_STATUS)
        assert "error" in wan.parse_status("garbage")

    def test_返回键集合固定(self):
        assert set(wan.parse_status(REAL_STATUS)) == wan.STATUS_KEYS
        assert set(wan.parse_status("")) == wan.STATUS_KEYS


# ── 重拨命令 ────────────────────────────────────────────────────
class TestRedialCommand:
    def test_用ifdown加ifup而非重启整机(self):
        cmd = wan.build_redial_command()
        assert "ifdown wan" in cmd
        assert "ifup wan" in cmd
        assert "reboot" not in cmd
        assert "init.d/network restart" not in cmd

    def test_重拨前有等待让链路先落(self):
        assert "sleep" in wan.build_redial_command()

    def test_输出重定向到日志文件并回显完成标记(self):
        cmd = wan.build_redial_command()
        assert "/tmp" in cmd
        assert "2>&1" in cmd
        assert wan.REDIAL_MARKER in cmd

    def test_接口名注入被拒(self):
        with pytest.raises(WanError):
            wan.build_redial_command("wan; reboot")

    def test_命令不超过真机单行上限(self):
        assert len(wan.build_redial_command()) < 500

    def test_日志读取与清理命令(self):
        assert wan.REDIAL_LOG in wan.build_redial_read_command()
        assert "rm -f" in wan.build_redial_cleanup_command()
        assert wan.REDIAL_LOG in wan.build_redial_cleanup_command()

    def test_重拨日志解析(self):
        got = wan.parse_redial_log("ifdown: 1\nYZ_REDIAL_SENT")
        assert got["sent"] is True
        assert "ifdown" in got["output"]

    def test_没收到完成标记判为未送达(self):
        got = wan.parse_redial_log("ifdown: 1")
        assert got["sent"] is False

    def test_日志解析遇None不抛(self):
        assert wan.parse_redial_log(None)["sent"] is False

    def test_重拨是分离执行的否则会撞读超时(self):
        # PPoE 的 ifup 要跑 LCP/PAP/IPCP 协商（实测常 3~10s），加上 ifdown 与
        # settle 等待会超过 telnet 12s 读超时 → 必须 `&` 放到后台立即返回
        cmd = wan.build_redial_command()
        assert cmd.rstrip().endswith("& echo " + wan.REDIAL_MARKER)
        assert "2>&1" in cmd and "</dev/null" in cmd

    def test_重拨日志轮询参数是有限次(self):
        # 自动轮询必须有上限，否则界面会永远转圈
        assert 1 <= wan.REDIAL_POLL_TIMES <= 8
        assert wan.REDIAL_POLL_MS >= 2000


# ── 文案 ────────────────────────────────────────────────────────
class TestTexts:
    def test_状态文案在线(self):
        text = wan.describe_status(wan.parse_status(REAL_STATUS))
        assert "100.67.227.167" in text
        assert "在线" in text

    def test_状态文案离线(self):
        text = wan.describe_status(wan.parse_status(
            json.dumps({"up": False, "available": True, "proto": "pppoe"})))
        assert "离线" in text

    def test_状态文案未知(self):
        text = wan.describe_status(wan.parse_status(""))
        assert "未知" in text

    def test_状态文案不含口令(self):
        text = wan.describe_status(wan.parse_status(REAL_STATUS))
        assert "a1b2c3d4" not in text

    def test_重拨确认文案点明会断网与影响(self):
        text = wan.redial_confirm_text("wan")
        assert "wan" in text
        assert "断" in text or "中断" in text

    def test_保存账号确认文案点明后果(self):
        text = wan.save_confirm_text("new@1", changing_password=True)
        assert "new@1" in text
        assert "口令" in text

    def test_保存账号确认文案不泄露口令明文(self):
        text = wan.save_confirm_text("new@1", changing_password=True)
        assert "hunter2" not in text

    def test_保存账号不变口令时文案说明不修改(self):
        text = wan.save_confirm_text("new@1", changing_password=False)
        assert "不修改口令" in text or "口令保持" in text

    def test_预览文案汇总改动(self):
        got = wan.describe_change(
            wan.parse_account(REAL_UCI),
            wan.parse_account(wan.apply_account(REAL_UCI, username="b@2")))
        assert any("" in str(i) for i in got)


# ── 上线时长格式化 ──────────────────────────────────────────────
class TestUptime:
    @pytest.mark.parametrize("secs,expect", [
        (0, "0 秒"), (59, "59 秒"), (60, "1 分 0 秒"),
        (3600, "1 时 0 分"), (86399, "23 时 59 分"), (90061, "1 天 1 时 1 分"),
    ])
    def test_格式化(self, secs, expect):
        assert wan.format_uptime(secs) == expect

    def test_负数与None安全(self):
        assert wan.format_uptime(None)
        assert wan.format_uptime(-5)


# ── 任务层：无变化绝不能写路由器 ─────────────────────────────────
class TestNoopDetection:
    """用真机录制（ReplaySession）驱动，替掉会「回固定值」的假 session。
    录制里未出现的命令会被 ReplaySession 判为失配 —— 代码漂移即红。"""

    RECORDING = pathlib.Path(__file__).parent / "fixtures" / "recordings" / "router-xiaomi-4a.json"
    #: 同一台设备，但「备份读回」那一步输出为空 —— 用于钉住中止分支。
    BACKUP_EMPTY_RECORDING = (pathlib.Path(__file__).parent / "fixtures" / "recordings"
                              / "router-xiaomi-4a-backup-empty.json")

    def _session(self, path=None):
        s = ReplaySession.from_file(str(path or self.RECORDING))
        s.open()
        return s

    @staticmethod
    def _network_and_username():
        data = json.loads(TestNoopDetection.RECORDING.read_text(encoding="utf-8"))
        text = data["steps"][0]["recv"]
        user = wan.parse_account(config_editor.parse_uci(text))["username"]
        return text, user

    def test_带注释的原始文本不被误判为有变化(self):
        from modules.router_admin.workers_wan import wan_save_worker
        _text, user = self._network_and_username()
        s = self._session()
        got = wan_save_worker(user, None)(s)
        assert got.get("stage") == "noop", got
        assert "无变化" in got.get("error", "")
        assert s.consumed == 1, "无变化时绝不能下发读以外的任何命令"

    def test_只改口令也算有变化(self):
        """钉住**可观测副作用**，而不只是「不是 noop」。

        只断言 `stage != "noop"` 的弱版本让整条写路径可以被悄悄改坏而仍全绿
        （层 D 审查实测：把 workers.py 里「远端备份内容为空，已中止写入」的守卫
        关掉，整套 router 测试依旧全绿）。下面两条断言让这种改动立刻变红：

        - `ok is True`：路由器回了 YZ_WRITE_OK，写入确实发生；
        - `backup` 非空且文件可读回：**备份未落盘就写配置正是 2026-09-29 备份
          损坏事故的模式**。备份内容必须是配置正文，读回来只有 `YZ_WRITE_OK`
          那种「假 session 时代」产物同样算失败。
        """
        from modules.router_admin import backup
        from modules.router_admin.workers_wan import wan_save_worker
        text, user = self._network_and_username()
        s = self._session()
        got = wan_save_worker(user, "brandnew")(s)
        assert got.get("stage") == "write", got
        assert got.get("ok") is True, f"写入未生效：{got}"
        assert got.get("password_changed") is True
        assert s.remaining == 0, "完整写路径必须与录制逐步吻合"
        # 备份必须真的落到本地，且落的是配置正文而不是写回标记
        path = got.get("backup")
        assert path, f"备份未落盘就写了配置（2026-09-29 事故模式）：{got}"
        saved = backup.read_backup(path)
        assert saved is not None, f"备份路径不可读回：{path}"
        assert saved == text, "备份内容不是读回的 network 正文"
        assert "YZ_WRITE_OK" not in saved
        # 写后回读校验的输出（steps[4].recv）此前零断言：这里钉住 worker 确实把
        # `build_verify_command` 的返回值透出来了，而不是写后压根没回读。
        fixture = json.loads(self.RECORDING.read_text(encoding="utf-8"))
        assert got.get("verified") == fixture["steps"][4]["recv"], (
            f"写后回读校验的输出未被断言：{got.get('verified')!r}")

    def test_代码发出未录制的命令_回放必须失败(self):
        """层 D 负向验证：改动命令即失配变红，不再静默通过。"""
        s = self._session()
        with pytest.raises(AssertionError):
            s.run("rm -rf /etc/config/network")

    def test_备份读回为空_必须中止且不下发写与校验(self):
        """备份读回为空 = 没有安全网，此时**绝不能**继续写配置。

        用 `router-xiaomi-4a-backup-empty.json`：第 3 步（备份读回）recv 为空串。
        `backup_then_write` 在这一步就返回 `ok=False, stage="backup"`，因此写与
        回读校验两条命令都不该下发，`remaining == 2` 正好是这两条。

        守卫一旦被摘掉，写命令会**匹配上**第 4 步（用户名与录制一致、口令命中
        `***` 通配），序列并不会用尽；红来自下面 `stage == "backup"` 那条断言
        ——那时 `stage` 已是 `"write"`。2026-09-29 之后那个守卫正是唯一挡住
        无备份写配置的东西。
        """
        from modules.router_admin import backup
        from modules.router_admin.workers_wan import wan_save_worker
        _text, user = self._network_and_username()
        s = self._session(self.BACKUP_EMPTY_RECORDING)
        got = wan_save_worker(user, "brandnew")(s)
        assert got.get("stage") == "backup", got
        assert got.get("ok") is False
        assert "备份内容为空" in got.get("error", "")
        # 消费了 3 步（读配置 / 远端 cp / 备份读回），写与校验两条从未下发
        assert s.consumed == 3 and s.remaining == 2, (
            f"中止后不该再下发写与校验命令（consumed={s.consumed}）")
        assert "backup" not in got, "中止时不得留下本地备份路径"
        assert not (os.path.isdir(backup.BACKUP_DIR)
                    and os.listdir(backup.BACKUP_DIR)), "中止时不得写本地备份"


# ── 持久化资源隔离（AGENTS.md 规则 7）────────────────────────────────
#
# 事故背景（2026-09-29）：本文件上面的 `TestNoopDetection` 曾用假 session 驱动
# `wan_save_worker` → `backup_then_write` → `backup.save_backup()`。假 session
# 对任何命令都回 `YZ_WRITE_OK`，于是 4 份「备份」内容全是 `YZ_WRITE_OK`
# 而不是配置正文，被写进了生产的 data/router_admin/backups/。
#
# 危害不是那 4 个文件本身，而是**安全网失效**：备份里没有可回滚的内容，写配置
# 出事时 `read_backup()` 取回来的东西毫无意义。这类污染只有靠 autouse 隔离
# 根治，所以断言落在 conftest 的重定向上，而不是某个用例上。
#
# 下面两个用例断言的是「隔离生效」这个属性本身；真正驱动写路径的是
# TestNoopDetection（现已改用真机录制回放），它们与本类共用 conftest 的
# autouse 隔离。


class TestPersistentIsolation:

    def test_备份目录不在生产DATA_DIR下(self):
        from core.constants import DATA_DIR
        from modules.router_admin import backup
        prod = os.path.abspath(DATA_DIR)
        assert not os.path.abspath(backup.BACKUP_DIR).startswith(prod), (
            f"backup.BACKUP_DIR 仍指向生产数据目录：{backup.BACKUP_DIR}")

    def test_设置文件不在生产DATA_DIR下(self):
        from core.constants import DATA_DIR
        from modules.router_admin import store
        prod = os.path.abspath(DATA_DIR)
        assert not os.path.abspath(store.SETTINGS_PATH).startswith(prod), (
            f"store.SETTINGS_PATH 仍指向生产数据目录：{store.SETTINGS_PATH}")



