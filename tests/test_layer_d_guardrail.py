"""tests/test_layer_d_guardrail.py：层 D（路由器 Telnet 录制回放）的不变量守卫。

层 D 的立身之本是「严格失配 + 严格脱敏」。这两条一旦被悄悄削弱，套件仍然全绿：
审查实测过把 `workers.py` 里「远端备份内容为空，已中止写入」的守卫关掉，
router 测试无一变红；也实测过把真实宽带账号与 MAC 留在夹具里推到公开仓库。

本文件把两条不变量变成**在 CI 里可证伪**的断言：

1. **凭据守卫**：录制夹具里不出现任何已知真实凭据字面量，且口令位恒为 `***`；
2. **漂移守卫**：命令构造函数一旦产出与录制不同的命令，回放必须抛
   `AssertionError`（而不是静默通过）——即「层 D 是活的」这件事本身要被断言。

纯数据 + 无网络的离线测试。测试模块顶层无副作用（不读文件、不改环境）。
"""
import json
import pathlib
import re

import pytest

from modules.router_admin import config_editor
from modules.router_admin.replay import ReplaySession

RECORDINGS_DIR = pathlib.Path(__file__).parent / "fixtures" / "recordings"
MAIN_RECORDING = RECORDINGS_DIR / "router-xiaomi-4a.json"

#: 2026-09-29 真机上出现过的真实凭据字面量。仓库要推到公开 GitHub/Gitee，
#: 任何一项出现在录制夹具里都必须让守卫变红。
KNOWN_REAL_SECRETS = (
    "07550000000@example.gd",     # 真实 PPPoE 宽带账号
    "02:00:00:00:00:01",         # 真实 WAN 口 MAC
    "fakepw01",                  # 真实宽带口令
)

_PASSWORD_RE = re.compile(r"option\s+password\s+'([^']*)'")


def _recordings():
    files = sorted(RECORDINGS_DIR.glob("*.json"))
    assert files, f"{RECORDINGS_DIR} 下没有任何录制夹具，守卫会静默放行"
    return files


# ── 凭据守卫 ────────────────────────────────────────────────────


def test_夹具不含任何已知真实凭据():
    for path in _recordings():
        text = path.read_text(encoding="utf-8")
        for secret in KNOWN_REAL_SECRETS:
            assert secret not in text, (
                f"{path.name} 含真实凭据 {secret!r}：录制会推到公开仓库，"
                f"必须换成虚构值")


def test_夹具里每个option_password位都是通配占位():
    """口令位恒为 `***`（:data:`REDACTED`）。

    账号/MAC 换成虚构值而不是 `***`：`***` 在回放时是**通配**（任意口令都匹配），
    拿来占账号/MAC 会让这些位置对任何值都匹配，削弱漂移检出。
    """
    for path in _recordings():
        data = json.loads(path.read_text(encoding="utf-8"))
        found = [m.group(1)
                 for step in data["steps"]
                 for m in _PASSWORD_RE.finditer(step.get("recv", ""))]
        assert found, f"{path.name} 里没有 option password 行，断言可能已失效"
        for value in found:
            assert value == "***", f"{path.name} 的口令位是 {value!r}，应为 '***'"


def test_账号与MAC是虚构值而非通配():
    """虚构账号/MAC 必须逐字出现在收发两侧，回放才能精确匹配。"""
    fake_account = "07550000000@example.gd"
    fake_mac = "02:00:00:00:00:01"
    data = json.loads(MAIN_RECORDING.read_text(encoding="utf-8"))
    text = data["steps"][0]["recv"]
    assert f"option username '{fake_account}'" in text
    assert f"option macaddr '{fake_mac}'" in text
    # 收发两侧一致 —— 不一致会让 write 步骤失配，测试会以误导性的方式变红
    assert f"option username '{fake_account}'" in data["steps"][3]["send"]
    assert f"option macaddr '{fake_mac}'" in data["steps"][3]["send"]


# ── 漂移守卫（层 D 的不变量本身要在 CI 里可证伪）────────────────


def test_读命令构造漂移_回放必须变红(monkeypatch):
    """`build_read_command` 一旦产出与录制不同的命令，回放必须抛 AssertionError。

    这是层 D 的核心不变量「代码漂移即红」的**自证**：如果哪天有人把
    `ReplaySession` 的严格匹配改成静默返回空串（正是层 D 文档里明确禁止的
    宽松化），这个用例会立刻变红 —— 否则「漂移即红」只是文档里的一句承诺。
    """
    from modules.router_admin.workers_wan import wan_save_worker

    original = config_editor.build_read_command
    monkeypatch.setattr(
        config_editor, "build_read_command",
        lambda section: original(section) + " ; sync")

    s = ReplaySession.from_file(str(MAIN_RECORDING))
    s.open()
    with pytest.raises(AssertionError):
        wan_save_worker("07550000000@example.gd", "brandnew")(s)
    assert s.consumed == 0, "失配不得消费步数"


def test_写命令构造漂移_回放必须变红(monkeypatch):
    """漂移注入到写命令构造上：走到第 4 步时失配，且不回退前面的步骤。

    只 monkeypatch `config_editor.build_write_command`，其余命令照旧按录制回放
    —— 证明守卫不是靠「一上来就错」侥幸通过的，而是真在逐步比对。
    """
    from modules.router_admin.workers_wan import wan_save_worker

    original = config_editor.build_write_command
    monkeypatch.setattr(
        config_editor, "build_write_command",
        lambda section, content: original(section, content) + " ; reboot")

    s = ReplaySession.from_file(str(MAIN_RECORDING))
    s.open()
    with pytest.raises(AssertionError):
        wan_save_worker("07550000000@example.gd", "brandnew")(s)
    assert s.consumed == 3, "前 3 步应按录制逐步吻合，第 4 步才失配"


def test_夹具自身与命令构造函数逐字吻合():
    """夹具的 `send` 必须由 `build_*` 产出 —— 夹具是现��的忠实记录，不是手写理想化替身。

    任何手写漂移都会在这里立刻暴露（比对是精确的，只有 `***` 是通配）。
    """
    from modules.router_admin import backup, wan
    from modules.router_admin.replay import redact

    data = json.loads(MAIN_RECORDING.read_text(encoding="utf-8"))
    text = data["steps"][0]["recv"]
    uci = config_editor.parse_uci(text)
    # 只改口令，正文与夹具第 4 步的 send 对应；口令按录制侧的 redact 抹成 ***
    after = wan.apply_account(uci, username=uci["interface"]["wan"]["username"],
                              password="brandnew")
    write = redact(config_editor.build_write_command(
        "network", config_editor.serialize_uci(after)), ["brandnew"])
    expected = [
        config_editor.build_read_command("network"),
        backup.build_remote_backup_command("network"),
        backup.build_remote_read_command("network"),
        write,
        config_editor.build_verify_command("network"),
    ]
    assert [step["send"] for step in data["steps"]] == expected


def test_写命令超过单条telnet上限_记录在案的既存缺陷():
    """层 D 已记录的既存生产缺陷：`build_write_command` 超 `CMD_CHAR_BUDGET`。

    宽带写路径的完整命令是 555 字符（含真实口令时 559），超过
    `workers.CMD_CHAR_BUDGET = 400`，也超过真机实测的 BusyBox tty 上限
    （450 可过 / 502 必挂）—— 真机上很可能发不出去。

    本批**未修**（超出层 D 范围），夹具保持对现状的忠实记录。这个用例的意义是
    把该事实钉在 CI 里：将来修好分块后它会变红，那时的正确反应是**按新命令
    序列重录夹具**，而不是放宽 `ReplaySession` 的匹配。
    """
    from modules.router_admin import workers

    data = json.loads(MAIN_RECORDING.read_text(encoding="utf-8"))
    write_cmd = data["steps"][3]["send"]
    assert len(write_cmd) > workers.CMD_CHAR_BUDGET, (
        "写命令已落在预算内：既存缺陷已修复，应重录夹具并删掉本用例的告警期望")