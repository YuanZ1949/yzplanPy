"""modules/router_admin 的文件大小棘轮：超 250 行只许减少，不许新增。

AGENTS.md 通用规范要求「单文件超过 250 行需拆分」。本包在层 D 收尾时已积了
4 个越线文件（历史遗留，登记在 `_GRANDFATHERED`），而「录制格式 v2 + 登录握手」
那批又把 `replay.py` 从 196 行推到 284 —— 于是把这条规范变成可证伪的断言：

- `_GRANDFATHERED` 之外的文件一律必须 ≤ 250 行（**新增越线即红**）；
- 已登记的文件只许减不许增：上限就是登记时的行数，再涨一行也红。

棘轮而非全量归零：历史遗留的拆分各自另立任务，本测试只保证欠债不再扩大。

纯 stdlib、无 Qt、只读源码文件。
"""
import pathlib

MODULE_DIR = (pathlib.Path(__file__).resolve().parent.parent
              / "modules" / "router_admin")

#: 已越线的历史遗留：文件名 → 当前行数上限（只许减，不许增）。
#: telnet.py / wan.py / workers.py / config_editor.py 的拆分各自另立任务。
_GRANDFATHERED = {
    "config_editor.py": 271,
    "telnet.py": 380,
    "wan.py": 306,
    "workers.py": 281,
}

_LIMIT = 250


def _line_count(path):
    return len(path.read_text(encoding="utf-8").splitlines())


def test_router_admin各文件不越250行棘轮():
    over = []
    for path in sorted(MODULE_DIR.glob("*.py")):
        allowed = max(_LIMIT, _GRANDFATHERED.get(path.name, 0))
        count = _line_count(path)
        if count > allowed:
            over.append(f"  {path.name}: {count} 行 > 上限 {allowed}")
    assert not over, (
        "单文件超过 250 行（AGENTS.md 通用规范）且未登记，请拆分：\n"
        + "\n".join(over))
