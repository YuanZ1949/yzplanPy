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
import hashlib
import json
import pathlib
import re

import pytest

from modules.router_admin import config_editor
from modules.router_admin.replay import ReplaySession

RECORDINGS_DIR = pathlib.Path(__file__).parent / "fixtures" / "recordings"
MAIN_RECORDING = RECORDINGS_DIR / "router-xiaomi-4a.json"

#: 2026-09-29 真机上出现过的真实凭据。仓库要推到公开 GitHub/Gitee，
#: 任何一项出现在录制夹具里都必须让守卫变红——但**不能存明文**：明文本身就是
#: 这里要防的那件泄漏。故只存 (长度, SHA-256)，扫描时按长度开窗哈希比对。
_KNOWN_REAL_SECRET_SHA256 = (
    (21, "ea10e8c09c752465536dfce23eaf15b2ad9ae7538696d691518428ccc8fedf18"),  # 真实 PPPoE 宽带账号
    (17, "d65e5189e6febfca5bd838f2ec08c6754f7045cadc0f83c5ce4b2695d769ad47"),  # 真实 WAN 口 MAC
    (8, "574b2d889c759d94299f348bbb5baa49970a93314dfeb8825e69b74d16326d45"),   # 真实宽带口令
)

_PASSWORD_RE = re.compile(r"option\s+password\s+'([^']*)'")


def _sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _find_known_secret(text, pairs=_KNOWN_REAL_SECRET_SHA256):
    """在 `text` 里按 (长度, SHA-256) 开窗查找；命中返回哈希，未命中返回 None。

    开窗哈希让守卫在**不存明文**的前提下保持与字面量扫描同等的检出能力。
    """
    for length, digest in pairs:
        if length <= 0 or length > len(text):
            continue
        for i in range(len(text) - length + 1):
            if _sha256_hex(text[i:i + length]) == digest:
                return digest
    return None


def _recordings():
    files = sorted(RECORDINGS_DIR.glob("*.json"))
    assert files, f"{RECORDINGS_DIR} 下没有任何录制夹具，守卫会静默放行"
    return files


# ── 凭据守卫 ────────────────────────────────────────────────────


def test_夹具不含任何已知真实凭据():
    for path in _recordings():
        text = path.read_text(encoding="utf-8")
        hit = _find_known_secret(text)
        assert hit is None, (
            f"{path.name} 含真实凭据（SHA-256 {hit[:12]}…）：录制会推到公开仓库，"
            f"必须换成虚构值")


def test_凭据检测器本身有效():
    """守卫不得静默失效：检测器要能命中植入的字符串，且不误报相邻串。"""
    planted = "PLACEHOLDER-SECRET-abcdef"
    pairs = ((len(planted), _sha256_hex(planted)),)
    assert _find_known_secret(f"prefix{planted}suffix", pairs) is not None
    assert _find_known_secret("prefixPLACEHOLDER-SECRET-abcdezsuffix", pairs) is None


def test_夹具里每个option_password位都是通配占位():
    """口令位恒为 `***`（:data:`REDACTED`），且**收发两侧都查**。

    账号/MAC 换成虚构值而不是 `***`：`***` 在回放时是**通配**（任意口令都匹配），
    拿来占账号/MAC 会让这些位置对任何值都匹配，削弱漂移检出。
    """
    for path in _recordings():
        data = json.loads(path.read_text(encoding="utf-8"))
        found = [(side, m.group(1))
                 for step in data["steps"]
                 for side in ("send", "recv")
                 for m in _PASSWORD_RE.finditer(step.get(side, ""))]
        assert found, f"{path.name} 里没有 option password 行，断言可能已失效"
        for side, value in found:
            assert value == "***", (
                f"{path.name} 的 {side} 侧口令位是 {value!r}，应为 '***'")
        # 写命令的正文就在 send 侧，必须证明这一侧真被扫到了；否则「口令恒为
        # ***」只是在 recv 上成立，send 侧仅靠字面量哈希兜底（审查点名的缺口）。
        assert any(side == "send" for side, _ in found), (
            f"{path.name} 的 send 侧没扫到 option password 行，不变量存在缺口")


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
    """夹具的 `send` 必须由 `build_*` 产出 —— 夹具是现状的忠实记录，不是手写理想化替身。

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


def test_写命令每行都在单行上限内_且真机确实写入成功():
    """真机约束是**单行**长度，不是命令总长——旧用例按总长报警属误用。

    宽带写命令是 heredoc：总长 555 字符，但最长单行只有 70 字符。同一台真机的
    录制里第 4 步 `recv == "YZ_WRITE_OK"`（`mv … && echo` 只有 mv 成功才会回），
    即真机确实把这条命令写进去了 —— 400 的「总长」预算对多行命令并不成立。
    `tests/test_router_config.py` 里有更精确的真机标定：约束对象是每一行
    （一行 493 字节可过 / 513 字节超时），多行 heredoc 不受总长约束。
    """
    data = json.loads(MAIN_RECORDING.read_text(encoding="utf-8"))
    write_cmd = data["steps"][3]["send"]
    assert data["steps"][3]["recv"] == "YZ_WRITE_OK", (
        "真机未回写成功标记：夹具或「555 字符可写」的结论需要复核")
    longest = max(write_cmd.splitlines(), key=len)
    assert len(longest) <= config_editor.MAX_TTY_LINE, (
        f"写命令最长单行 {len(longest)} 字符，超过 tty 单行上限 "
        f"{config_editor.MAX_TTY_LINE}")
    assert len(write_cmd) > config_editor.MAX_TTY_LINE, (
        "命令总长已落进单行预算，说明写命令形态变了：本用例与开发日志都要重看")


def test_写后回读校验的响应形状被钉住():
    """`steps[4].recv`（写后 `head -3` 回读）此前在 tests/ 下零断言。

    响应形状是层 D 的第三种可变异维度（前两种：读回内容、写命令），没人断言
    就等于让「写后回读拿到别的东西」也能全绿。这里按字面钉住头部三行。
    """
    data = json.loads(MAIN_RECORDING.read_text(encoding="utf-8"))
    assert data["steps"][4]["send"] == config_editor.build_verify_command("network")
    assert data["steps"][4]["recv"] == (
        "# 由固件生成，请勿手改\n"
        "config interface 'loopback'\n"
        "\toption proto 'static'")
