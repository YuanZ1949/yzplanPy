# 右键菜单管理模块（right_menu 一期）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 YZplan「右键菜单」模块一期（M1–M7）：扫描/开关四类右键项、管理新建菜单、经典菜单开关、自定义右键项、YZplan 系统右键子菜单、MCP 切片。

**Architecture:** 分层——UI（`modules/right_menu/widgets/`）→ 操作层（`scan/ops/shellnew/classic/custom/yzmenu`，纯 Python 不 import PySide6）→ 注册表后端（`registry_backend.py`，Protocol + Win32/Fake）→ 账本（`store.py`）→ 提权通道（`elevate.py` + `main.py --elevated-job` 早退通道）。全部注册表写操作先经账本备份，UI 只做组装与事件转发（阻塞操作用 QThread）。

**Tech Stack:** Python 3.11 / 标准库（winreg、ctypes、json、subprocess）+ PySide6/qfluentwidgets（仅 UI 层）。

**Spec:** `docs/superpowers/specs/2026-10-05-right-menu-manager-design.md`

## Global Constraints

- 操作层模块（`registry_backend/scan/ops/shellnew/classic/custom/yzmenu/store/elevate`）**禁止 import PySide6**；UI 层才允许。
- **Qt 导入纪律**：`main.py --elevated-job` 早退通道必须在一切 Qt import 与单实例互斥量**之前**；`modules/right_menu/__init__.py` 必须惰性导出（PEP 562），保证 `import modules.right_menu.elevate` 不触发 Qt。
- 测试**零真实注册表读写**：一律注入 `FakeRegistry`；HKLM 写一律经假 `elevate.run_job`；store/elevate 路径经 `tests/conftest.py` 隔离到 tmp。
- 路径经模块全局、调用时读取（沿 `proxy_ctrl/store.py` 先例），便于 monkeypatch。
- **相对导入层级（防写错点数）**：`widgets/` 下文件（page.py、home_widget.py）引 right_menu 顶层模块用 `from .. import store/classic/workers`；`widgets/page_tabs/` 下文件在第三级，用 `from ... import scan/workers/...`、`from ...registry_backend import Win32Backend`；引 widgets 助手统一 `from .. import confirm/make_card_block/notify`、`from ..tables import fill_table/make_table`。
- 所有注册表写操作前调用 `store.backup_snapshot()`（有账本时）；`state.json` 用原子写（临时文件 + `os.replace`）。
- GUI 样式：控件一律 `ui/widgets.py` 工厂；颜色取 `theme_palette()`、尺寸取 `sizing()`；禁止 hex/rgba 字面量与手写像素；改动后跑 `python scripts/audit_styles.py --check`（不得新增违规）与 `python -m pytest tests/test_style_guardrails.py -v`。
- 单文件 ≤ 250 行；超限按职责拆分。
- TDD：每任务先写失败测试→跑失败→实现→跑通→commit（conventional commits，中文正文）。
- 新测试文件必须登记进 `.github/workflows/python-app.yml` 的 4 个 chunk（本计划统一在 Task 21 登记）。
- 除既有依赖外**不引入新依赖**（一期纯 Python）。

## Review Focus

以下五类输入/失败模式最容易咬用户，各自归属任务已加测试（见每任务 Test 步骤）：

1. 注册表里出现**非字符串值**（REG_DWORD/REG_BINARY 挂在 MUIVerb/默认值上）→ 扫描显示必须 `str()` 兜底不崩（Task 4）。
2. 自定义项占位符 `%1` 未加引号、路径含空格 → 保存时必须给**警告**而非静默生成坏命令（Task 9）。
3. ShellNew 已隐藏项再次隐藏 / 隐藏→恢复→隐藏往返 → 值名**不得叠加后缀**（幂等）（Task 8）。
4. 账本指向的注册表键**被外部删除**后执行恢复/删除 → 静默成功、不抛错（Task 6）。
5. `state.json` 损坏或半写（上次崩溃）→ `load()` 返回空账本；`save()` 原子替换不留半文件（Task 3）。

## 文件结构

```
modules/right_menu/
  __init__.py            惰性导出 MODULE_INFO / Module（PEP 562 __getattr__）
  module.py              ModuleBase 子类；start/stop；dispatch_menu_action
  registry_backend.py    Hive 常量、RegistryBackend Protocol、Win32Backend、FakeRegistry
  store.py               账本 state.json + backups/ + restore_all
  scan.py                MenuItem、SCOPES、scan_scope
  ops.py                 原语构造与统一操作 apply_op（disable/restore/delete）
  shellnew.py            ShellNew 扫描/隐藏/恢复/新增
  classic.py             经典菜单状态/开关/重启 explorer
  custom.py              自定义项校验/命令展开/投影/sync/CRUD
  yzmenu.py              YZplan 系统右键子菜单安装/卸载/状态
  elevate.py             提权作业 + 原语执行 + argv 助手 + menu-action 转发
  workers.py             TaskGroup/JobContext（镜像 proxy_ctrl/workers.py）
  widgets/
    __init__.py          UI 助手（confirm/notify/alert/make_card_block 等，镜像 proxy_ctrl）
    tables.py            令牌化 QTableWidget 工厂 + 填充助手（actions 支持 callable(row)）
    home_widget.py       首页小卡
    page.py              RightMenuPage（frameless + 5 标签壳 + title_bar_spec）
    page_tabs/
      __init__.py        标签类导出
      scan_tab.py        右键项标签（扫描/搜索/隐藏恢复）
      shellnew_tab.py    新建菜单标签
      classic_tab.py     经典菜单标签
      custom_tab.py      自定义项标签
      settings_tab.py    设置标签（YZplan 菜单/一键还原/备份）
    editor_dialog.py     自定义项编辑器（多级子菜单树）
    restore_dialog.py    一键还原确认
mcp_server/tools_right_menu.py
tests/test_right_menu_{store,scan,ops,shellnew,classic,custom,yzmenu,elevate,ui,mcp}.py
```

**与 spec 文件清单的差异（已记录）**：① spec §11 授权「page.py 超限时拆 page_tabs/*」，本计划直接按 250 行规则预拆；② 新增 `workers.py`（QThread 编排，镜像 proxy_ctrl）与 `tests/test_right_menu_mcp.py`（spec 测试表未单列 MCP 测试）；③ `store.py` 记录确认：spec §5.3 提到 rename，但 §16 明确排除右键项重命名 → **不实现 rename**。

**任务 ↔ 里程碑**：M1 = T1-T4 + T12-T14；M2 = T5-T6；M3 = T7 + T16；M4 = T8 + T15；M5 = T9 + T17；M6 = T10 + T18 + T19；M7 = T20。T11/T21 为跨里程碑收尾（一键还原、CI 登记与全量验收）。任务按 T1→T21 线性执行，里程碑用于验收分组；spec 的 M1「新建菜单只读标签」并入 T15（与 M4 后端同任务交付），其余与 spec 一致。M8（Rust+稀疏包）不属本计划。

**修改的既有文件**：`main.py`、`core/tray/mcp.py`、`mcp_server/__init__.py`、`tests/conftest.py`、`tests/test_mcp_tray.py`、`.gitignore`、`.github/workflows/python-app.yml`。

---

### Task 1: 包骨架与惰性导出

**Files:**
- Create: `modules/right_menu/__init__.py`
- Create: `modules/right_menu/module.py`
- Test: `tests/test_right_menu_ui.py`

**Interfaces:**
- Consumes: `modules/base.py::ModuleBase`
- Produces: `modules.right_menu.MODULE_INFO / Module`（惰性）；`Module.MODULE_ID="right_menu"`；`create_home_widget/create_page` 惰性 import 后续任务的 widgets；`dispatch_menu_action(action)` 占位（Task 16 实现）。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_ui.py
import importlib

def test_module_info_contract():
    mod = importlib.import_module("modules.right_menu")
    assert mod.MODULE_INFO["id"] == "right_menu"
    assert mod.MODULE_INFO["name"] and mod.MODULE_INFO["description"]
    assert issubclass(mod.Module, __import__("modules.base", fromlist=["ModuleBase"]).ModuleBase)
    assert mod.Module.MODULE_ID == "right_menu"

def test_lazy_export_via_getattr():
    mod = importlib.import_module("modules.right_menu")
    assert mod.Module.MODULE_ID == mod.MODULE_INFO["id"]  # 两次 __getattr__ 均可用
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: FAIL（ModuleNotFoundError: modules.right_menu）

- [x] **Step 3: 实现**

`modules/right_menu/__init__.py`：只定义 `__all__ = ["MODULE_INFO", "Module"]` 与 PEP 562 `def __getattr__(name)`（`MODULE_INFO`→`from .module import MODULE_INFO`；`Module`→`from .module import Module`；其余 `AttributeError`）。**不得**在包顶层 import 任何子模块。

`modules/right_menu/module.py`：`MODULE_INFO` dict（id/name="右键菜单"/description 概括七项功能） + `class Module(ModuleBase)`（类属性 `MODULE_ID/MODULE_NAME/MODULE_DESCRIPTION/MODULE_VERSION="0.1"/ENABLED_BY_DEFAULT=True`；`__init__` 调 super 并存 `_home_timer=None/_home_widget=None`；`start/stop` 先只调 super；`create_home_widget/create_page` 返回 None 由后续任务替换为惰性 import；`dispatch_menu_action` 置空方法由 Task 16 实装）。本任务 module.py **不得 import Qt**。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: 2 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/__init__.py modules/right_menu/module.py tests/test_right_menu_ui.py
git commit -m "feat(right_menu): 模块骨架与惰性导出"
```

---

### Task 2: registry_backend（Protocol + Win32 + Fake）

**Files:**
- Create: `modules/right_menu/registry_backend.py`
- Test: `tests/test_right_menu_scan.py`

**Interfaces:**
- Produces: 常量 `HKCU="HKCU"`、`HKLM="HKLM"`；`class RegistryBackend(Protocol)`；`class Win32Backend`（永不抛异常，错→None/[]）；`class FakeRegistry`（内存树，与 Win32Backend 行为对齐，测试注入）。六个方法签名：`get(hive, path, name=None)->str|None` / `set(hive, path, name, value)` / `delete(hive, path, name=None)`（不存在静默成功）/ `delete_tree(hive, path)` / `list_keys(hive, path)->list[str]` / `list_values(hive, path)->list[tuple[str,str]]`。

- [x] **Step 1: 写失败测试**（FakeRegistry 语义先行；scan 测试 Task 4 追加到本文件）

```python
from modules.right_menu.registry_backend import FakeRegistry

def test_fake_set_get_roundtrip():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Demo", "", "Demo")
    r.set("HKCU", r"Software\Classes\*\shell\Demo", "MUIVerb", "演示")
    assert r.get("HKCU", r"Software\Classes\*\shell\Demo") == "Demo"      # 默认值
    assert r.get("HKCU", r"Software\Classes\*\shell\Demo", "MUIVerb") == "演示"

def test_fake_missing_returns_none_and_silent_delete():
    r = FakeRegistry()
    assert r.get("HKCU", r"Software\Nope") is None
    assert r.get("HKCU", r"Software\Nope", "x") is None
    r.delete("HKCU", r"Software\Nope", "x")   # 静默成功
    r.delete_tree("HKCU", r"Software\Nope")   # 静默成功

def test_fake_list_keys_and_values():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\A", "", "A")
    r.set("HKCU", r"Software\Classes\*\shell\B", "", "B")
    assert sorted(r.list_keys("HKCU", r"Software\Classes\*\shell")) == ["A", "B"]
    r.set("HKCU", r"Software\Classes\*\shell\A", "Extended", "")
    assert set(r.list_values("HKCU", r"Software\Classes\*\shell\A")) == {("", "A"), ("Extended", "")}

def test_fake_delete_tree_removes_descendants():
    r = FakeRegistry()
    r.set("HKCU", r"k\a\b", "v", "1")
    r.delete_tree("HKCU", r"k")
    assert r.get("HKCU", r"k\a\b", "v") is None
    assert r.list_keys("HKCU", r"k") == []

def test_win32_backend_never_raises(monkeypatch):
    import sys
    from modules.right_menu import registry_backend as rb
    monkeypatch.setitem(sys.modules, "winreg", None)   # import winreg 抛 ImportError
    b = rb.Win32Backend()
    assert b.get("HKCU", r"Software\Nope") is None
    assert b.list_keys("HKCU", r"Software\Nope") == []
    assert b.list_values("HKCU", r"Software\Nope") == []
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_scan.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

`Win32Backend`：六个方法各自 `try: import winreg; OpenKeyEx(KEY_READ) ... except OSError/ImportError/ValueError: return 兜底`；值统一 `str()` 化（bytes 用 `decode(errors="replace")`）；hive 映射 `{"HKCU": HKEY_CURRENT_USER, "HKLM": HKEY_LOCAL_MACHINE}`；`name=None` 即 winreg 默认值 `""`。`FakeRegistry`：`self._tree: dict[tuple[str,str], dict[str,str]]`（路径 casefold 归一化存 key；另存原始段名以便 list_keys 返回原样）+ 同名方法；`list_keys` 返回直接子键段名（排序无关，测试自排）。两实现均含 `delete_tree` 删除自身与所有后代。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_scan.py -v`
Expected: 5 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/registry_backend.py tests/test_right_menu_scan.py
git commit -m "feat(right_menu): 注册表后端 Protocol 与 Fake/ Win32 实现"
```

---

### Task 3: store 账本（原子写 + 备份快照）

**Files:**
- Create: `modules/right_menu/store.py`
- Modify: `tests/conftest.py`（`_isolate_db` 追加 store 路径隔离）
- Modify: `.gitignore`（追加 `data/right_menu/`）
- Test: `tests/test_right_menu_store.py`

**Interfaces:**
- Consumes: 无（纯 JSON）。
- Produces: 模块全局 `STATE_PATH/BACKUP_DIR/TEMPLATES_DIR`（`<DATA_DIR>/right_menu/...`，调用时读取）；`SCHEMA=1`、`MAX_BACKUPS=30`；`_empty_state()->dict`（schema/disabled/shellnew_hidden/custom_items/yzmenu/restore_points）；`load()->dict`（损坏返空）；`save(state)->bool`（原子）；`backup_snapshot(reason)->str|None`（写 `backups/<ts>_<slug>.json`，超 MAX_BACKUPS 剪枝）；变更助手 `add_disabled/remove_disabled/add_shellnew_hidden/remove_shellnew_hidden/get_custom_items/set_custom_items/set_yzmenu/add_restore_point`（均 load→改→save，返 bool）。`restore_all` 由 Task 11 追加。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_store.py
import json, os
from modules.right_menu import store

def test_load_empty_and_corrupted_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    assert store.load()["disabled"] == []
    with open(store.STATE_PATH, "w", encoding="utf-8") as f:
        f.write("{broken json")
    assert store.load()["schema"] == 1 and store.load()["disabled"] == []

def test_save_is_atomic_and_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    st = store._empty_state()
    st["disabled"].append({"hive": "hkcu", "key_path": "k", "name": "LegacyDisable", "original": None, "ts": "t"})
    assert store.save(st) is True
    assert store.load()["disabled"][0]["key_path"] == "k"
    assert not os.path.exists(store.STATE_PATH + ".tmp")   # 原子写不留半文件

def test_mutators_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    assert store.add_disabled("hkcu", r"Software\Classes\*\shell\X", None)
    assert store.add_shellnew_hidden("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile")
    assert store.set_custom_items([{"id": "1", "title": "T"}])
    assert store.set_yzmenu(True, ["open_manager"])
    assert store.load()["disabled"][0]["key_path"].endswith("X")
    assert store.remove_disabled("hkcu", r"Software\Classes\*\shell\X")
    assert store.load()["disabled"] == []

def test_backup_snapshot_writes_file_and_prunes(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(store, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(store, "MAX_BACKUPS", 3)
    for i in range(5):
        assert store.backup_snapshot(f"op{i}") is not None
    files = os.listdir(store.BACKUP_DIR)
    assert len(files) == 3   # 剪枝到上限
    data = json.load(open(os.path.join(store.BACKUP_DIR, sorted(files)[-1]), encoding="utf-8"))
    assert data["schema"] == 1
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_store.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

- 全局：`_RM_DIR = os.path.join(DATA_DIR, "right_menu")`；`STATE_PATH/_BACKUP_DIR/TEMPLATES_DIR` 三个叶全局（函数内读全局，勿缓存到局部闭包）。
- `save`：`os.makedirs(dirname)` → 写 `STATE_PATH + ".tmp"` → `os.replace` → True；OSError/ValueError → False。
- `backup_snapshot`：先 `save(load())` 保证源文件存在？否——直接 copy 当前 `load()` 结果 json 写出（不用 copy 文件，避免把半写文件拷走）；文件名 `time.strftime("%Y%m%d_%H%M%S") + "_" + re.sub(r'\W+','_',reason)[:40] + ".json"`（同秒冲突加序号）；写后按 mtime 排序保留 MAX_BACKUPS。返回路径。
- 变更助手：统一 `state = load(); ...; save(state)`。
- `.gitignore`：在 `data/proxy_ctrl/` 相邻处追加 `data/right_menu/`。
- `conftest.py`：`_isolate_db` 内 `import modules.right_menu.store as rm_store`，monkeypatch `STATE_PATH/BACKUP_DIR/TEMPLATES_DIR` 到 `tmp_path/"right_menu/..."`（Task 5 再补 elevate.JOB_DIR）。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_store.py -v`
Expected: 4 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/store.py tests/test_right_menu_store.py tests/conftest.py .gitignore
git commit -m "feat(right_menu): 账本 store（原子写/备份/隔离）"
```

---

### Task 4: scan 四作用域扫描

**Files:**
- Create: `modules/right_menu/scan.py`
- Test: `tests/test_right_menu_scan.py`（追加）

**Interfaces:**
- Consumes: `registry_backend`。
- Produces: `SCOPES=("file","directory","background","drive")`；`SCOPE_ROOTS` dict；`scan_scope(backend, scope, *, include_hklm=True)->list[dict]`。MenuItem dict 字段：`scope/hive/key_path/display_name/command/icon/extended/disabled/children/builtin`（`key_path` 为相对 hive 的路径，如 `Software\Classes\*\shell\7-Zip`；`children` 为同构 dict 列表）。

- [x] **Step 1: 写失败测试**

```python
from modules.right_menu.registry_backend import FakeRegistry
from modules.right_menu import scan

def _seed(r):
    r.set("HKCU", r"Software\Classes\*\shell\SevenZip", "", "7-Zip")
    r.set("HKCU", r"Software\Classes\*\shell\SevenZip", "MUIVerb", "7-Zip 菜单")
    r.set("HKCU", r"Software\Classes\*\shell\SevenZip\command", "", r'"C:\7z.exe" "%1"')
    r.set("HKCU", r"Software\Classes\*\shell\ExtOnly", "MUIVerb", "Shift 项")
    r.set("HKCU", r"Software\Classes\*\shell\ExtOnly", "Extended", "")
    r.set("HKCU", r"Software\Classes\*\shell\Hidden", "", "隐藏项")
    r.set("HKCU", r"Software\Classes\*\shell\Hidden", "LegacyDisable", "")
    r.set("HKLM", r"Software\Classes\*\shell\SysWide", "", "系统项")
    r.set("HKLM", r"Software\Classes\*\shell\SysWide\command", "", "sys.exe")

def test_scan_file_scope_fields():
    r = FakeRegistry(); _seed(r)
    items = scan.scan_scope(r, "file")
    by_name = {i["display_name"]: i for i in items}
    it = by_name["7-Zip 菜单"]            # MUIVerb 优先
    assert it["hive"] == "hkcu" and it["key_path"].endswith(r"shell\SevenZip")
    assert it["command"] == r'"C:\7z.exe" "%1"' and it["extended"] is False
    assert by_name["Shift 项"]["extended"] is True
    assert by_name["隐藏项"]["disabled"] is True
    assert by_name["系统项"]["hive"] == "hklm"

def test_scan_skip_hklm_when_disabled():
    r = FakeRegistry(); _seed(r)
    assert all(i["hive"] == "hkcu" for i in scan.scan_scope(r, "file", include_hklm=False))

def test_scan_default_value_fallback_and_keyname_fallback():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\WithDefault", "", "默认名")
    r.set("HKCU", r"Software\Classes\*\shell\Bare", "", "")
    items = scan.scan_scope(r, "file")
    by = {i["key_path"].rsplit("\\", 1)[-1]: i for i in items}
    assert by["WithDefault"]["display_name"] == "默认名"
    assert by["Bare"]["display_name"] == "Bare"      # 空默认值回退键名

def test_scan_submenu_children():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Parent", "MUIVerb", "父菜单")
    r.set("HKCU", r"Software\Classes\*\shell\Parent", "SubCommands", "")
    r.set("HKCU", r"Software\Classes\*\shell\Parent\shell\Child", "", "子项")
    r.set("HKCU", r"Software\Classes\*\shell\Parent\shell\Child\command", "", "child.exe")
    parent = [i for i in scan.scan_scope(r, "file") if i["display_name"] == "父菜单"][0]
    assert parent["children"][0]["display_name"] == "子项"
    assert parent["children"][0]["command"] == "child.exe"

def test_scan_nonstring_values_coerced():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Num", "MUIVerb", 5)   # 模拟非字符串值
    items = scan.scan_scope(r, "file")
    assert items[0]["display_name"] == "5"

def test_scan_order_disabled_last():
    r = FakeRegistry(); _seed(r)
    items = scan.scan_scope(r, "file")
    flags = [i["disabled"] for i in items]
    assert flags == sorted(flags)      # 禁用项排在最后

def test_scan_scopes_paths():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\Directory\shell\DT", "", "文件夹项")
    r.set("HKCU", r"Software\Classes\Directory\Background\shell\BG", "", "背景项")
    r.set("HKCU", r"Software\Classes\Drive\shell\DR", "", "驱动器项")
    assert scan.scan_scope(r, "directory")[0]["display_name"] == "文件夹项"
    assert scan.scan_scope(r, "background")[0]["display_name"] == "背景项"
    assert scan.scan_scope(r, "drive")[0]["display_name"] == "驱动器项"
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_scan.py -v`
Expected: 新增测试 FAIL（scan 不存在）

- [x] **Step 3: 实现**

- `SCOPE_ROOTS`：`file`=[`Software\Classes\*`, `Software\Classes\AllFilesystemObjects`]；`directory`=[`Software\Classes\Directory`]；`background`=[`Software\Classes\Directory\Background`]；`drive`=[`Software\Classes\Drive`]。
- 枚举：对每个 root×hive → `list_keys(backend, root + r"\shell")`；跳过名为 `shellex`/`ShellEx` 的子键；递归子菜单：同 key 存在 `SubCommands` 值或存在 `shell` 子键时读 `...\shell` 子键。
- 显示名：`MUIVerb`（空串视为无）> 默认值（空串视为无）> 键名；`MUIVerb` 以 `@` 开头时原样显示并加后缀「（间接字符串）」。
- 命令：`key\command` 默认值；无则查 `DelegateExecute` 值（存在则 `command=f"(DelegateExecute) {v}"`）；都无 → `command=None` 且 `builtin=True`（无子键时）。`icon`：`Icon` 值，否则 `key\DefaultIcon` 默认值；无则 None。所有取值 `str()` 兜底（None/空串转 `""` → 视为无）。
- 排序：`sorted(enabled, key=lambda i: i["display_name"].casefold()) + sorted(disabled, ...)`。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_scan.py -v`
Expected: 全部通过（Fake 5 + scan 7）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/scan.py tests/test_right_menu_scan.py
git commit -m "feat(right_menu): 四作用域右键项扫描"
```

### Task 5: elevate 提权作业 + `--elevated-job` 早退通道

**Files:**
- Create: `modules/right_menu/elevate.py`
- Modify: `main.py`（顶部插入早退通道）
- Modify: `tests/conftest.py`（`_isolate_db` 追加 elevate.JOB_DIR 隔离）
- Test: `tests/test_right_menu_elevate.py`

**Interfaces:**
- Consumes: `registry_backend`。
- Produces: `JOB_DIR`（模块全局，调用时读取）；`set_op(hive,path,name,value)->dict` / `delete_op(hive,path,name=None)->dict` / `delete_tree_op(hive,path)->dict`；`exec_ops(backend, ops)->list[dict]`；`_job_path(job_id)` / `_result_path(job_id)`；`run_elevated_job(job_path, *, backend=None)->int`；`build_launch_cmd(job_path)->list[str]`；`launch(job_path, *, shell_execute=None)->dict`；`run_job(job, *, timeout=60.0, launch_fn=None, poll_interval=0.2)->dict`；`menu_action_command(action)->dict`；`forward_menu_action(action, *, inbox_dir=None)->bool`。作业原语：`{"action":"set"|"delete"|"delete_tree","hive","path","name"?,"value"?}`；作业文件 `{"id","ops":[...]}`；结果 `{"id","ok","error","results"}`。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_elevate.py
"""提权作业通道：序列化/执行/超时/UAC 取消映射/main 早退端到端/Qt 隔离。"""
import json, os, subprocess, sys

from modules.right_menu import elevate
from modules.right_menu.registry_backend import FakeRegistry


def test_exec_ops_primitives():
    r = FakeRegistry()
    r.set("hkcu", r"k\b", "x", "1")
    r.set("hkcu", r"k\c\deep", "y", "1")
    results = elevate.exec_ops(r, [
        elevate.set_op("hkcu", r"k\a", "", "v"),
        elevate.delete_op("hkcu", r"k\b", "x"),
        elevate.delete_tree_op("hkcu", r"k\c"),
    ])
    assert all(x["ok"] for x in results)
    assert r.get("hkcu", r"k\a") == "v"
    assert r.get("hkcu", r"k\b", "x") is None
    assert r.get("hkcu", r"k\c\deep", "y") is None


def test_run_elevated_job_roundtrip(tmp_path):
    r = FakeRegistry()
    job_path = str(tmp_path / "job_t1.json")
    json.dump({"id": "t1", "ops": [elevate.set_op("hkcu", r"k", "name", "val")]},
              open(job_path, "w", encoding="utf-8"))
    assert elevate.run_elevated_job(job_path, backend=r) == 0
    result = json.load(open(str(tmp_path / "job_t1.result.json"), encoding="utf-8"))
    assert result["ok"] is True and r.get("hkcu", r"k", "name") == "val"


def test_run_elevated_job_missing_file_returns_1(tmp_path):
    assert elevate.run_elevated_job(str(tmp_path / "nope.json"), backend=FakeRegistry()) == 1


def test_run_job_reads_child_result(tmp_path, monkeypatch):
    monkeypatch.setattr(elevate, "JOB_DIR", str(tmp_path / "elevated"))

    def fake_launch(job_path, **kw):        # 模拟提权子进程立即写结果
        jid = json.load(open(job_path, encoding="utf-8"))["id"]
        json.dump({"id": jid, "ok": True, "error": None},
                  open(elevate._result_path(jid), "w", encoding="utf-8"))
        return {"ok": True, "error": None, "code": 42}

    out = elevate.run_job({"ops": []}, timeout=2.0, launch_fn=fake_launch, poll_interval=0.05)
    assert out["ok"] is True


def test_run_job_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(elevate, "JOB_DIR", str(tmp_path / "elevated"))
    out = elevate.run_job({"ops": []}, timeout=0.3,
                          launch_fn=lambda p, **k: {"ok": True, "error": None, "code": 42},
                          poll_interval=0.05)
    assert out["ok"] is False and out["error"] == "timeout"


def test_build_launch_cmd_frozen_and_dev(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = elevate.build_launch_cmd(r"C:\tmp\j.json")
    assert cmd[0] == sys.executable and cmd[-2:] == ["--elevated-job", r"C:\tmp\j.json"]
    monkeypatch.delattr(sys, "frozen")
    cmd = elevate.build_launch_cmd(r"C:\tmp\j.json")
    assert any(str(x).endswith("main.py") for x in cmd) and cmd[-2:] == ["--elevated-job", r"C:\tmp\j.json"]


def test_launch_maps_cancel_and_success():
    out = elevate.launch(r"C:\tmp\j.json", shell_execute=lambda exe, params, cwd: 5)
    assert out["ok"] is False and out["error"] == "cancelled"    # SE_ERR_ACCESSDENIED：用户点了“否”
    out = elevate.launch(r"C:\tmp\j.json", shell_execute=lambda exe, params, cwd: 42)
    assert out["ok"] is True


def test_forward_menu_action_writes_inbox(tmp_path):
    assert elevate.forward_menu_action("open_manager", inbox_dir=str(tmp_path))
    name = [f for f in os.listdir(tmp_path) if f.endswith(".json")][0]
    payload = json.load(open(os.path.join(tmp_path, name), encoding="utf-8"))
    assert payload["command"] == "menu_action" and payload["action"] == "open_manager"


def test_import_elevate_does_not_load_qt():
    code = ("import sys; import modules.right_menu.elevate; "
            "mods = set(sys.modules); "
            "assert not any(m.startswith('PySide6') for m in mods), 'PySide6 loaded'; "
            "assert 'qfluentwidgets' not in mods and 'core.qt_bootstrap' not in mods; "
            "print('OK')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd())
    assert out.returncode == 0, out.stderr
    assert "OK" in out.stdout


def test_main_early_exit_channel(tmp_path):
    """main.py --elevated-job 必须在 Qt/互斥量之前早退并写结果（端到端）。"""
    job_path = tmp_path / "job_e2e.json"
    job_path.write_text(json.dumps({"id": "e2e", "ops": []}), encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "main.py", "--elevated-job", str(job_path)],
                         capture_output=True, text=True, cwd=os.getcwd(), env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    result = json.loads((tmp_path / "job_e2e.result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_elevate.py -v`
Expected: FAIL（ModuleNotFoundError / main.py 无早退通道）

- [x] **Step 3: 实现**

`elevate.py`（纯 Python，禁 Qt）：
- `JOB_DIR = os.path.join(DATA_DIR, "right_menu", "elevated")`（调用时读全局）；`_job_path(job_id)=os.path.join(JOB_DIR, f"job_{job_id}.json")`；`_result_path(job_id)` = `os.path.splitext(_job_path(job_id))[0] + ".result.json"`。
- `exec_ops(backend, ops)`：逐条 `try` 执行；`set`→`backend.set(hive,path,name or "",value or "")`；`delete`→`backend.delete(hive,path,name)`；`delete_tree`→`backend.delete_tree(hive,path)`；未知 action→`{"ok":False,"error":"unknown_action: X"}`。
- `run_elevated_job(job_path, *, backend=None)`：读 JSON（OSError/ValueError→返 1，不写结果）；`ops` 非 list→结果 `{"ok":False,"error":"bad_job"}` 写盘返 1；执行后写 `{"id","ok","error","results"}` 到 `splitext(job_path)[0]+".result.json"`；全 ok 返 0 否则 1。backend 缺省惰性 `Win32Backend()`。
- `build_launch_cmd(job_path)` 镜像 `core/restart.py` 的双模式：frozen→`[sys.executable, "--elevated-job", job_path]`；dev→`[pythonw(存在时)或sys.executable, PROJECT_DIR/main.py, "--elevated-job", job_path]`。`_launch_cwd()`：frozen→exe 目录，dev→PROJECT_DIR。
- `launch(job_path, *, shell_execute=None)`：`cmd=build_launch_cmd`；`exe=cmd[0]`，`params=subprocess.list2cmdline(cmd[1:])`；缺省 `shell_execute=_shell_execute_runas(exe,params,cwd)`（`ctypes.windll.shell32.ShellExecuteW(None,"runas",exe,params,cwd,1)`，异常→0）；`code>32`→`{"ok":True,"error":None,"code":code}`；`code==5`→`{"ok":False,"error":"cancelled"}`；其余→`{"ok":False,"error":"launch_failed"}`。
- `run_job(job, *, timeout=60.0, launch_fn=None, poll_interval=0.2)`：`job_id=uuid4().hex`；`os.makedirs(JOB_DIR)`；写 `_job_path`；`launch_fn or launch`（失败→返回其 error）；轮询 `_result_path` 至 deadline（`json.load` 的 ValueError 视为未写完，继续等）；读到→返回 dict（确保含 `"ok"`）；超时→`{"ok":False,"error":"timeout"}`。作业/结果文件保留供排查。
- `menu_action_command(action)`→`{"command":"menu_action","action":action,"silent":True,...}`（含 uuid id 与 time，与 `_mcp_inbox_command` 风格一致）；`forward_menu_action(action, *, inbox_dir=None)`：目录缺省 `os.path.join(DATA_DIR,"mcp_inbox")`，写 `<uuid>.json`，异常返 False。

`main.py` 早退通道（锚点：stderr 重定向 try/except 块之后、`# 单实例互斥量必须放在...` 注释块之前）：

```python
# ── right_menu 提权作业早退通道 ─────────────────────────────────────
# 必须在任何 Qt import 与单实例互斥量之前执行：本进程由 elevate.run_job()
# 以 runas 拉起，只执行注册表原语后立即退出。不创建 QApplication、不碰
# 互斥量，因此不会与正在运行的主实例冲突。
if sys.platform == "win32" and "--elevated-job" in sys.argv:
    try:
        _job_path = sys.argv[sys.argv.index("--elevated-job") + 1]
        from modules.right_menu.elevate import run_elevated_job
        sys.exit(run_elevated_job(_job_path))
    except Exception:
        sys.exit(1)
```

`tests/conftest.py`：`_isolate_db` 内 `import modules.right_menu.elevate as rm_elevate`，`monkeypatch.setattr(rm_elevate, "JOB_DIR", str(tmp_path / "right_menu" / "elevated"))`。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_elevate.py -v`
Expected: 10 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/elevate.py main.py tests/conftest.py tests/test_right_menu_elevate.py
git commit -m "feat(right_menu): 提权作业通道与 --elevated-job 早退"
```

---

### Task 6: ops 统一操作（隐藏/恢复/删除）

**Files:**
- Create: `modules/right_menu/ops.py`
- Test: `tests/test_right_menu_ops.py`

**Interfaces:**
- Consumes: `registry_backend`、`store`、`elevate.run_job/set_op/delete_op`（Task 5）。
- Produces: `apply_op(backend, op: dict, *, store_mod=None) -> {"ok": bool, "detail": str}`。op 形态：`{"action":"disable"|"restore"|"delete","hive":"hkcu"|"hklm","key_path":str,"name"?:str,"original"?:str|None,"builtin"?:bool}`。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_ops.py
from modules.right_menu import ops, store
from modules.right_menu.registry_backend import FakeRegistry

KEY = r"Software\Classes\*\shell\Demo"


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))


def test_disable_hkcu_writes_legacy_and_ledger(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry(); r.set("hkcu", KEY, "", "Demo")
    backups = []
    monkeypatch.setattr(ops.store, "backup_snapshot", lambda reason: backups.append(reason))
    assert ops.apply_op(r, {"action": "disable", "hive": "hkcu", "key_path": KEY})["ok"]
    assert r.get("hkcu", KEY, "LegacyDisable") == ""
    assert store.load()["disabled"][0]["key_path"] == KEY
    assert backups      # 写前必须备份


def test_restore_roundtrip_clears_ledger(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry(); r.set("hkcu", KEY, "", "Demo")
    ops.apply_op(r, {"action": "disable", "hive": "hkcu", "key_path": KEY})
    assert ops.apply_op(r, {"action": "restore", "hive": "hkcu", "key_path": KEY})["ok"]
    assert r.get("hkcu", KEY, "LegacyDisable") is None
    assert store.load()["disabled"] == []


def test_hklm_disable_goes_through_elevate(monkeypatch):
    jobs = []
    monkeypatch.setattr(ops.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    r = FakeRegistry()
    out = ops.apply_op(r, {"action": "disable", "hive": "hklm", "key_path": KEY})
    assert out["ok"] and jobs[0]["ops"][0]["action"] == "set"
    assert r.get("hklm", KEY, "LegacyDisable") is None   # 不得直写


def test_hklm_cancelled_reports_friendly(monkeypatch):
    monkeypatch.setattr(ops.elevate, "run_job", lambda job, **k: {"ok": False, "error": "cancelled"})
    out = ops.apply_op(FakeRegistry(), {"action": "disable", "hive": "hklm", "key_path": KEY})
    assert out["ok"] is False and "取消" in out["detail"]


def test_delete_protections():
    r = FakeRegistry()
    assert not ops.apply_op(r, {"action": "delete", "hive": "hklm", "key_path": KEY})["ok"]
    assert not ops.apply_op(r, {"action": "delete", "hive": "hkcu", "key_path": KEY, "builtin": True})["ok"]
    r.set("hkcu", KEY, "", "Demo")
    assert ops.apply_op(r, {"action": "delete", "hive": "hkcu", "key_path": KEY})["ok"]
    assert r.get("hkcu", KEY) is None


def test_restore_missing_key_is_silent_ok():
    assert ops.apply_op(FakeRegistry(), {"action": "restore", "hive": "hkcu", "key_path": KEY})["ok"]


def test_unknown_action_rejected():
    assert not ops.apply_op(FakeRegistry(), {"action": "rename", "hive": "hkcu", "key_path": KEY})["ok"]
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ops.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

- `from . import elevate, store`；`hive = str(op.get("hive","")).lower()`，仅接受 `hkcu/hklm`。
- 校验顺序：未知 action→拒绝；缺 `key_path`→拒绝；`delete` 且 hive!=hkcu→「HKLM 项仅支持隐藏」；`delete` 且 `builtin`→「系统内建项不可删除」。
- 统一先 `store.backup_snapshot(f"{action} {key_path}")`（store_mod 参数用以注入，默认本模块 store）。
- `hkcu` 直写：disable→`backend.set("hkcu", key_path, "LegacyDisable", "")` + `store.add_disabled`；restore→`backend.delete(..., op.get("name") or "LegacyDisable")`（`original` 非 None 时先 `set` 回原值）+ `store.remove_disabled`；delete→`backend.delete_tree` + `store.remove_disabled`。
- `hklm` 经 `elevate.run_job({"ops":[...]})`：disable→`[set_op(hive,key_path,"LegacyDisable","")]`；restore→`[delete_op(...)]`（+original 恢复用 set_op 在前）；job 失败→`{"ok":False,"detail": {"cancelled":"已取消（UAC 被拒绝），未做任何修改","timeout":"未收到提权结果，请稍后重试"}.get(err, "提权作业失败")}`；成功才更新账本。
- 返回 `{"ok": True, "detail": "已完成: <action> <key_path>"}`。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ops.py -v`
Expected: 7 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/ops.py tests/test_right_menu_ops.py
git commit -m "feat(right_menu): 原语操作层（LegacyDisable 隐藏/恢复/删除）"
```

---

### Task 7: classic 经典菜单开关

**Files:**
- Create: `modules/right_menu/classic.py`
- Test: `tests/test_right_menu_classic.py`

**Interfaces:**
- Consumes: `registry_backend`。
- Produces: `CLASSIC_CLSID="{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"`、`CLSID_KEY`、`INPROC_KEY`；`get_classic_state(backend)->"enabled"|"disabled"|"unknown"`；`enable_classic(backend)->dict`；`disable_classic(backend)->dict`；`restart_explorer(*, runner=None)->dict`。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_classic.py
import os
from modules.right_menu import classic
from modules.right_menu.registry_backend import FakeRegistry


def test_state_three_values():
    r = FakeRegistry()
    assert classic.get_classic_state(r) == "disabled"           # 键不存在 = 新版菜单
    r.set("hkcu", classic.INPROC_KEY, "", "")
    assert classic.get_classic_state(r) == "enabled"            # 空默认值 = 经典
    r.set("hkcu", classic.INPROC_KEY, "", r"C:\other.dll")
    assert classic.get_classic_state(r) == "unknown"            # 非本机制的 COM 注册


def test_toggle_roundtrip():
    r = FakeRegistry()
    assert classic.enable_classic(r)["ok"]
    assert classic.get_classic_state(r) == "enabled"
    assert classic.disable_classic(r)["ok"]
    assert classic.get_classic_state(r) == "disabled"
    assert r.get("hkcu", classic.CLSID_KEY) is None


def test_restart_explorer_command():
    calls = []
    out = classic.restart_explorer(runner=lambda cmd: calls.append(cmd))
    assert out["ok"] is True
    joined = " ".join(calls[0])
    assert "taskkill" in joined and "explorer.exe" in joined and "start" in joined


def test_restart_explorer_failure():
    def boom(cmd): raise OSError("denied")
    out = classic.restart_explorer(runner=boom)
    assert out["ok"] is False
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_classic.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

- `CLSID_KEY = rf"Software\Classes\CLSID\{{{CLASSIC_CLSID}}}"`；`INPROC_KEY = CLSID_KEY + r"\InprocServer32"`。
- `get_classic_state`：`v = backend.get("hkcu", INPROC_KEY) if key exists`——键存在性用 `INPROC_KEY in [CLSID_KEY + "\\InprocServer32"]`… 简化判定：`backend.get("hkcu", INPROC_KEY)` 为 `""`→enabled；为 `None`→再查 `backend.list_values("hkcu", CLSID_KEY)`：空→disabled（键不存在），非空但 InprocServer32 无默认值→unknown；为非空字符串→unknown。
- `enable_classic`：`backend.set("hkcu", INPROC_KEY, "", "")`→`{"ok":True,"detail":"已切换到经典菜单（需重启资源管理器生效）"}`。
- `disable_classic`：`backend.delete_tree("hkcu", CLSID_KEY)`→ok（键不存在也 ok）。
- `restart_explorer(*, runner=None)`：`cmd=["cmd","/c","taskkill /f /im explorer.exe & start explorer.exe"]`；缺省 runner=`subprocess.Popen`；try/except→`{"ok":False,"detail":"请手动重启资源管理器"}`。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_classic.py -v`
Expected: 4 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/classic.py tests/test_right_menu_classic.py
git commit -m "feat(right_menu): 经典菜单总开关与 explorer 重启"
```

---

### Task 8: shellnew 新建菜单管理

**Files:**
- Create: `modules/right_menu/shellnew.py`
- Test: `tests/test_right_menu_shellnew.py`

**Interfaces:**
- Consumes: `registry_backend`、`store`、`elevate`。
- Produces: `HIDDEN_SUFFIX="__yzhidden"`、`EXT_RE`；`scan_shellnew(backend)->list[dict]`（item：`hive/ext/key_path/kind/values/hidden/template`，kind∈`null|template|data|command|unknown`）；`hide_shellnew(backend,item,*,store_mod=None)->dict`；`restore_shellnew(backend,item,*,store_mod=None)->dict`；`create_shellnew(backend,ext,*,name,kind,template_path=None,store_mod=None)->dict`；`delete_shellnew(backend,item,*,store_mod=None)->dict`。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_shellnew.py
import os
from modules.right_menu import shellnew, store
from modules.right_menu.registry_backend import FakeRegistry

SN = r"Software\Classes\.xyz\ShellNew"


def test_scan_finds_hkcu_and_hklm():
    r = FakeRegistry()
    r.set("hkcu", SN, "NullFile", "")
    r.set("hklm", r"Software\Classes\.abc\ShellNew", "FileName", r"C:\tpl\abc.tpl")
    by = {i["ext"]: i for i in shellnew.scan_shellnew(r)}
    assert by[".xyz"]["kind"] == "null" and by[".xyz"]["hive"] == "hkcu"
    assert by[".abc"]["kind"] == "template" and by[".abc"]["hive"] == "hklm"
    assert by[".abc"]["template"] == r"C:\tpl\abc.tpl"


def test_hide_restore_roundtrip_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    r = FakeRegistry(); r.set("hkcu", SN, "NullFile", "DATA")
    item = shellnew.scan_shellnew(r)[0]
    assert shellnew.hide_shellnew(r, item)["ok"]
    assert r.get("hkcu", SN, "NullFile__yzhidden") == "DATA"
    assert r.get("hkcu", SN, "NullFile") is None
    assert shellnew.hide_shellnew(r, item)["ok"]              # 幂等：不叠加后缀
    assert r.get("hkcu", SN, "NullFile__yzhidden") == "DATA"
    assert shellnew.restore_shellnew(r, item)["ok"]
    assert r.get("hkcu", SN, "NullFile") == "DATA"
    assert store.load()["shellnew_hidden"] == []


def test_create_null_and_reject_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    r = FakeRegistry()
    assert shellnew.create_shellnew(r, ".xyz", name="空文件", kind="null")["ok"]
    assert r.get("hkcu", SN, "NullFile") == ""
    assert not shellnew.create_shellnew(r, ".xyz", name="重复", kind="null")["ok"]   # 已存在拒绝


def test_create_template_copies_file(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(store, "TEMPLATES_DIR", str(tmp_path / "tpl"))
    src = tmp_path / "mytpl.txt"; src.write_text("x", encoding="utf-8")
    r = FakeRegistry()
    assert shellnew.create_shellnew(r, ".txt2", name="模板", kind="template",
                                    template_path=str(src))["ok"]
    fn = r.get("hkcu", r"Software\Classes\.txt2\ShellNew", "FileName")
    assert fn and os.path.isfile(fn) and os.path.basename(fn).endswith("mytpl.txt")


def test_invalid_ext_rejected():
    r = FakeRegistry()
    for bad in ("xyz", r"..\evil", ".", "." + "x" * 40):
        assert not shellnew.create_shellnew(r, bad, name="x", kind="null")["ok"]


def test_hklm_hide_routes_elevation_and_delete_protection(monkeypatch):
    jobs = []
    monkeypatch.setattr(shellnew.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    r = FakeRegistry(); r.set("hklm", SN, "NullFile", "D")
    item = [i for i in shellnew.scan_shellnew(r) if i["hive"] == "hklm"][0]
    assert shellnew.hide_shellnew(r, item)["ok"] and jobs
    assert r.get("hklm", SN, "NullFile") == "D"               # 未直写
    assert not shellnew.delete_shellnew(r, item)["ok"]        # HKLM 仅隐藏
    r.set("hkcu", SN, "NullFile", "D")
    item2 = [i for i in shellnew.scan_shellnew(r) if i["hive"] == "hkcu"][0]
    assert shellnew.delete_shellnew(r, item2)["ok"]
    assert r.get("hkcu", SN) is None
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_shellnew.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

- `EXT_RE = re.compile(r"^\.[A-Za-z0-9_.-]{1,30}$")`；`HIDDEN_SUFFIX="__yzhidden"`；`_CANON = ("NullFile","FileName","Data","Command")`。
- `scan_shellnew`：对 `hkcu/hklm` × `Software\Classes` 一层子键（`list_keys`）筛 `.` 开头；`"ShellNew" in backend.list_keys(hive, ext_key)` 才收录；`values=list_values`；`hidden=all(v 名带后缀)`（存在任意带后缀值即 True）；`template`=FileName 值（去后缀名匹配）；kind 派生：带后缀名去后缀后匹配 canon。
- `hide_shellnew`：item 已 hidden→`{"ok":True,"detail":"已隐藏"}`（幂等）；原值名 = 首个未带后缀的 canon 名；hkcu→`delete`+`set(name+suffix,data)`；hklm→`elevate.run_job({"ops":[delete_op,set_op]})`；成功后 `store_mod.add_shellnew_hidden(hive, key_path, name)`；写前 `backup_snapshot`。
- `restore_shellnew`：未 hidden→幂等 ok；`delete(name+suffix)`+`set(name,data)`（hklm 走作业）；`store_mod.remove_shellnew_hidden`。
- `create_shellnew`：校验 `EXT_RE`（否则「扩展名格式无效」）与 `kind in ("null","template")`；目标键 `Software\Classes\<ext>\ShellNew` 已有值→「已存在同名项」；null→`set(...,"NullFile","")`；template→`template_path` 必须为已存在文件，复制到 `store_mod.TEMPLATES_DIR`（`uuid4().hex[:8] + "_" + os.path.basename(src)`），`set(...,"FileName", 绝对路径)`；写前备份。
- `delete_shellnew`：hklm→拒绝（「系统项仅支持隐藏」）；hkcu→backup + `delete_tree`。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_shellnew.py -v`
Expected: 6 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/shellnew.py tests/test_right_menu_shellnew.py
git commit -m "feat(right_menu): ShellNew 新建菜单扫描/隐藏/恢复/新增"
```

### Task 9: custom 自定义项（校验/展开/投影/sync/CRUD）

**Files:**
- Create: `modules/right_menu/custom.py`
- Test: `tests/test_right_menu_custom.py`

**Interfaces:**
- Consumes: `registry_backend`、`elevate`（set_op/delete_tree_op/exec_ops/run_job）、`store`。
- Produces: `validate_item(item)->{"ok":bool,"errors":[...],"warnings":[...]}`；`expand_command(item,*,selected=None,current_dir=None)->str`（**预览/告警用**；注册表写入保持占位符原样，由 shell 展开）；`slugify(item)->str`（确定性：标题净化 + "_" + id[:6]）；`save_item(backend,item,*,store_mod=None)->dict`；`delete_item(backend,item_id,*,store_mod=None)->dict`；`sync_all(backend,*,store_mod=None)->dict`；`export_items(path)->dict`；`import_items(backend,path,*,store_mod=None)->dict`。DOM 按 spec §5.6（id/title/icon/scope/ext_filter/hive/extended/position/action{kind,target,args,workdir}/children）。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_custom.py
from modules.right_menu import custom, store
from modules.right_menu.registry_backend import FakeRegistry


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))


def _item(**kw):
    base = {"id": "a1", "title": "用记事本打开", "icon": "", "scope": "file",
            "ext_filter": [], "hive": "hkcu", "extended": False,
            "position": "bottom",
            "action": {"kind": "program", "target": r"C:\Windows\notepad.exe",
                       "args": '"%1"', "workdir": ""},
            "children": []}
    base.update(kw)
    return base


def test_validate_rejects_and_warns():
    out = custom.validate_item(_item(action={"kind": "program", "target": "", "args": ""}))
    assert not out["ok"] and out["errors"]
    out = custom.validate_item(_item(action={"kind": "program", "target": "x", "args": "%1"}))
    assert out["ok"] and any("引号" in w for w in out["warnings"])       # 未引号占位符→警告
    out = custom.validate_item(_item(action={"kind": "program", "target": "x", "args": "%q"}))
    assert any("占位" in w for w in out["warnings"])                     # 未识别占位符→警告


def test_expand_command_placeholders():
    it = _item()
    cmd = custom.expand_command(it, selected=[r"C:\My Docs\a.txt"], current_dir=r"C:\My Docs")
    assert r'"C:\My Docs\a.txt"' in cmd and r'"C:\My Docs"' in cmd
    assert "%1" in custom.expand_command(it)                             # 无选中时保留占位符


def test_sync_creates_projection_and_values(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert custom.save_item(r, _item())["ok"]
    p = r"Software\Classes\*\shell\用记事本打开_a1"
    assert r.get("hkcu", p, "MUIVerb") == "用记事本打开"
    assert r.get("hkcu", p + r"\command") == r"C:\Windows\notepad.exe " + '"%1"'
    assert store.load()["custom_items"][0]["id"] == "a1"


def test_sync_ext_filter_uses_system_file_associations(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert custom.save_item(r, _item(ext_filter=[".py", ".txt"]))["ok"]
    assert r.get("hkcu", r"Software\Classes\SystemFileAssociations\.py\shell\用记事本打开_a1",
                 "MUIVerb") == "用记事本打开"
    assert r.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1") is None


def test_sync_submenu_structure(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    child = _item(id="c1", title="子项",
                  action={"kind": "open", "target": r"C:\tmp\a.txt", "args": "", "workdir": ""})
    it = _item(id="p1", title="父菜单", children=[child])
    assert custom.save_item(r, it)["ok"]
    parent = r"Software\Classes\*\shell\父菜单_p1"
    assert r.get("hkcu", parent, "SubCommands") == ""
    assert r.get("hkcu", parent + r"\shell\子项_c1", "MUIVerb") == "子项"


def test_sync_idempotent_and_repositions(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    it = _item()
    assert custom.save_item(r, it)["ok"]
    assert custom.save_item(r, it)["ok"]                                  # 二次保存幂等
    it2 = dict(it, scope="directory")
    assert custom.save_item(r, it2)["ok"]
    assert r.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1") is None  # 旧投影被清
    assert r.get("hkcu", r"Software\Classes\Directory\shell\用记事本打开_a1",
                 "MUIVerb") == "用记事本打开"


def test_delete_removes_projection_and_ledger(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    custom.save_item(r, _item())
    assert custom.delete_item(r, "a1")["ok"]
    assert r.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1") is None
    assert store.load()["custom_items"] == []


def test_hklm_sync_routes_elevate(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    jobs = []
    monkeypatch.setattr(custom.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    r = FakeRegistry()
    assert custom.save_item(r, _item(hive="hklm"))["ok"] and jobs
    assert r.get("hklm", r"Software\Classes\*\shell\用记事本打开_a1") is None  # 未直写


def test_export_import_roundtrip(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    custom.save_item(r, _item())
    out_path = str(tmp_path / "items.json")
    assert custom.export_items(out_path)["ok"]
    r2 = FakeRegistry()
    assert custom.import_items(r2, out_path)["ok"]
    assert r2.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1")
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_custom.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

- `slugify`：标题保留 `[0-9A-Za-z_\u4e00-\u9fff]`，其余→`_`，截 32 字符，空则 `item`；最终 `<净名>_<id[:6]>`（确定性 → sync 幂等）。
- 投影路径（按 item 的 scope）：`file` 无 filter→`Software\Classes\*\shell\<slug>`；`file` 带 filter→每扩展名 `Software\Classes\SystemFileAssociations\<ext>\shell\<slug>`；`directory/background/drive`→`Software\Classes\{Directory|Directory\Background|Drive}\shell\<slug>`（扩展名先经 shellnew.EXT_RE 同款校验，非法→错误）。旧投影清除：`sync_all`/`save_item` 对旧 item 的全部投影路径 `delete_tree`。
- 写节点（含 children 递归）：父键值 `MUIVerb`=title、`SubCommands`=""、"Icon"（非空才写）、"Extended"（true 才写空值）、"Position"（top→"Top"/bottom→"Bottom"）；每节点 `command` 子键默认值 = `target + " " + args`（原样保留占位符）；child 用 child 自己的 slug。
- 写通道：把「delete_tree 旧路径 + set 全部新值」组织为 ops 列表（用 `elevate.set_op/delete_tree_op`）；`hive=="hkcu"` → `elevate.exec_ops(backend, ops)` 本地执行；`hive=="hklm"` → `elevate.run_job({"ops": ops})`，失败文案映射同 Task 6。
- `validate_item`：errors=空 target / 非法 kind / 非法 scope / 非法扩展名；warnings=`%1|%*|%V` 未处于双引号内（含空格路径风险）、`%` 后跟未识别字符、target/args 含 `cmd /c`（提示示例确认）。
- `save_item`：validate→错误直接返回；upsert 进 `store.set_custom_items`（按 id 替换，追加保序）；再 sync（旧 item 从 store 快照取）；返回 `{"ok","detail","warnings"}`。`delete_item`：查 store→删投影→从 store 移除。`export_items(path)`：写 `{"schema":1,"items":[...]}`；`import_items`：逐条 validate（跳过非法并在 detail 汇报）、按 id upsert、sync_all。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_custom.py -v`
Expected: 9 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/custom.py tests/test_right_menu_custom.py
git commit -m "feat(right_menu): 自定义项校验/展开/投影/CRUD"
```

---

### Task 10: yzmenu 系统右键子菜单

**Files:**
- Create: `modules/right_menu/yzmenu.py`
- Test: `tests/test_right_menu_yzmenu.py`

**Interfaces:**
- Consumes: `registry_backend`、`store`。
- Produces: `ACTIONS=["open_manager","toggle_classic","show_window","restore_all"]`；`ACTION_LABELS` dict；`action_command(action)->str`（完整命令行，含 `--menu-action`）；`install_yzmenu(backend,actions,*,store_mod=None)->dict`；`uninstall_yzmenu(backend,*,store_mod=None)->dict`；`get_yzmenu_state(backend)->{"installed":bool,"actions":[...]}`。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_yzmenu.py
from modules.right_menu import store, yzmenu
from modules.right_menu.registry_backend import FakeRegistry


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))


def test_install_creates_three_roots_and_actions(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert yzmenu.install_yzmenu(r, ["open_manager", "toggle_classic"])["ok"]
    for root in ("*", "Directory", r"Directory\Background"):
        p = rf"Software\Classes\{root}\shell\YZplan"
        assert r.get("hkcu", p, "MUIVerb") == "YZplan"
        assert r.get("hkcu", p, "SubCommands") == ""
        assert r.get("hkcu", p, "Position") == "Top"
    cmd = r.get("hkcu", r"Software\Classes\*\shell\YZplan\shell\open_manager")
    assert "--menu-action open_manager" in cmd
    st = store.load()["yzmenu"]
    assert st["installed"] is True and st["actions"] == ["open_manager", "toggle_classic"]


def test_state_and_uninstall(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert yzmenu.get_yzmenu_state(r) == {"installed": False, "actions": []}
    yzmenu.install_yzmenu(r, ["show_window"])
    state = yzmenu.get_yzmenu_state(r)
    assert state["installed"] is True and state["actions"] == ["show_window"]
    assert yzmenu.uninstall_yzmenu(r)["ok"]
    assert yzmenu.get_yzmenu_state(r)["installed"] is False
    assert r.get("hkcu", r"Software\Classes\Directory\shell\YZplan") is None


def test_unknown_action_rejected():
    assert not yzmenu.install_yzmenu(FakeRegistry(), ["nope"])["ok"]
    assert yzmenu.ACTION_LABELS["open_manager"] == "打开管理器"


def test_action_command_mentions_action():
    cmd = yzmenu.action_command("restore_all")
    assert "--menu-action" in cmd and "restore_all" in cmd
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_yzmenu.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

- `action_command(action)`：镜像 `core/restart.py` 双模式命令构造（frozen→`sys.executable`；dev→`.venv/Scripts/pythonw.exe` 或 `sys.executable` + `PROJECT_DIR/main.py`），再 `subprocess.list2cmdline([...] + ["--menu-action", action])`。
- 三根：`Software\Classes\{*|Directory|Directory\Background}\shell\YZplan`，父键 `MUIVerb="YZplan"`、`Icon`=exe 路径、`SubCommands=""`、`Position="Top"`；动作子键 `...\shell\YZplan\shell\<action>` 的默认值 = `action_command(action)`，`MUIVerb`=ACTION_LABELS。
- `install_yzmenu`：先校验 actions ⊆ ACTIONS；先 `uninstall` 旧键（幂等）再建；成功后 `store.set_yzmenu(True, actions)`；返回 `{"ok":True,"detail":...}`。
- `get_yzmenu_state`：installed = `*` 根父键存在；actions = `*` 根下 `shell` 子键名 ∩ 按 ACTIONS 顺序。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_yzmenu.py -v`
Expected: 4 passed

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/yzmenu.py tests/test_right_menu_yzmenu.py
git commit -m "feat(right_menu): YZplan 系统右键子菜单安装/卸载"
```

---

### Task 11: store.restore_all 一键还原

**Files:**
- Modify: `modules/right_menu/store.py`（追加函数，**惰性 import** 其他操作层模块避免循环）
- Test: `tests/test_right_menu_store.py`（追加；任务 11 的测试随本任务加入）

**Interfaces:**
- Consumes: `backend`、本模块账本；函数体内惰性 import `ops/shellnew/classic/custom/yzmenu`。
- Produces: `restore_all(backend)->{"ok":bool,"report":[{"kind":str,"detail":str,"ok":bool}]}`。撤销顺序：disabled→shellnew_hidden→custom_items→yzmenu→classic（跳过不存在的类别）；先 `backup_snapshot("restore_all")`；结束后账本对应数组清空 + `add_restore_point("restore_all", report)`；经典菜单仅当 `get_classic_state(backend)=="enabled"` 时 `disable_classic`。

- [x] **Step 1: 写失败测试**（追加到 `tests/test_right_menu_store.py`）

```python
def test_restore_all_reverts_and_clears_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(store, "BACKUP_DIR", str(tmp_path / "backups"))
    from modules.right_menu import classic, custom, yzmenu
    from modules.right_menu.registry_backend import FakeRegistry

    r = FakeRegistry()
    # 1) 被隐藏项
    r.set("hkcu", r"Software\Classes\*\shell\Demo", "", "Demo")
    store.add_disabled("hkcu", r"Software\Classes\*\shell\Demo", None)
    r.set("hkcu", r"Software\Classes\*\shell\Demo", "LegacyDisable", "")
    # 2) ShellNew 隐藏
    r.set("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile__yzhidden", "D")
    store.add_shellnew_hidden("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile")
    # 3) 自定义项（写投影 + 账本）
    custom.save_item(r, {"id": "a1", "title": "T", "icon": "", "scope": "file",
                         "ext_filter": [], "hive": "hkcu", "extended": False,
                         "position": "bottom",
                         "action": {"kind": "open", "target": r"C:\t.txt",
                                    "args": "", "workdir": ""},
                         "children": []})
    # 4) YZplan 子菜单 + 经典菜单
    yzmenu.install_yzmenu(r, ["open_manager"])
    classic.enable_classic(r)

    out = store.restore_all(r)
    assert out["ok"] and out["report"]
    assert r.get("hkcu", r"Software\Classes\*\shell\Demo", "LegacyDisable") is None
    assert r.get("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile") == "D"
    assert r.get("hkcu", r"Software\Classes\*\shell\T_a1") is None
    assert yzmenu.get_yzmenu_state(r)["installed"] is False
    assert classic.get_classic_state(r) == "disabled"
    st = store.load()
    assert st["disabled"] == [] and st["shellnew_hidden"] == [] and st["custom_items"] == []
    assert st["restore_points"] and st["restore_points"][-1]["reason"] == "restore_all"
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_store.py::test_restore_all_reverts_and_clears_ledger -v`
Expected: FAIL（AttributeError: restore_all）

- [x] **Step 3: 实现**

函数体内 `from . import classic, custom, shellnew, yzmenu`（惰性，规避 `custom→store` 循环）；逐类撤销并逐条记 report（单条失败不中断，记 `ok=False`）；shellnew 恢复需按 `item` 形态重建（用 `scan_shellnew` 当前态构造；找不到键→记「键已不存在，跳过」）；custom 用 `delete_item`（其内部也会改账本，最后统一再清一次为空是幂等的）；末尾 `save(state)`。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_store.py -v`
Expected: 5 passed（原 4 + 新增 1）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/store.py tests/test_right_menu_store.py
git commit -m "feat(right_menu): 一键还原 restore_all"
```

---

### Task 12: workers 线程封装

**Files:**
- Create: `modules/right_menu/workers.py`
- Test: `tests/test_right_menu_ui.py`（追加）

**Interfaces:**
- Consumes: `core.qt_bootstrap.import_qt`；操作层 `scan/shellnew/ops/classic/custom/yzmenu/store`。
- Produces: `describe_error(exc)->(kind,text)`；`JobContext`（`cancel` Event / `progress(done,total)` / `cancelled`）；`RightMenuTask(QThread)`（信号 `succeeded(object)/failed(str,str)/settled()`；`stop()`）；`TaskGroup(QObject)`（`busy`、`idle` 信号、`start(worker,*,on_ok,on_err,on_progress,label)`、`cancel()`、`shutdown()`）。worker 签名统一 `worker(ctx)->object`；任务函数：`scan_scope_worker(ctx,backend,scope)`、`scan_shellnew_worker(ctx,backend)`、`apply_op_worker(ctx,backend,op)`、`classic_state_worker(ctx,backend)`、`classic_set_worker(ctx,backend,enable)`、`save_item_worker(ctx,backend,item)`、`delete_item_worker(ctx,backend,item_id)`、`yzmenu_state_worker(ctx,backend)`、`yzmenu_install_worker(ctx,backend,actions)`、`restore_all_worker(ctx,backend)`。

- [x] **Step 1: 写失败测试**（追加到 `tests/test_right_menu_ui.py`）

```python
def test_task_group_runs_worker_and_settles(qapp):
    import time
    from modules.right_menu.workers import TaskGroup, describe_error
    done = {}
    g = TaskGroup()
    assert g.start(lambda ctx: {"v": 1}, on_ok=lambda r: done.update(r), label="t")
    deadline = time.time() + 5
    while g.busy and time.time() < deadline:
        qapp.processEvents(); time.sleep(0.01)
    assert done.get("v") == 1
    assert describe_error(ValueError("bad"))[0] == "invalid"


def test_task_group_rejects_when_busy(qapp):
    import time
    from modules.right_menu.workers import TaskGroup
    g = TaskGroup()
    g.start(lambda ctx: (time.sleep(0.2), {"v": 1})[1])
    assert g.start(lambda ctx: {"v": 2}) is False
    deadline = time.time() + 5
    while g.busy and time.time() < deadline:
        qapp.processEvents(); time.sleep(0.01)
    g.shutdown()
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: FAIL（ModuleNotFoundError: modules.right_menu.workers）

- [x] **Step 3: 实现**

镜像 `modules/proxy_ctrl/workers.py` 的线程层（`_JOIN_MS=4000`；`RightMenuTask` 与 `ProxyTask` 同构改名；`TaskGroup` 同构）；`describe_error` 文案：OSError→"系统调用失败：…"、ValueError→"参数不合法：…"、PermissionError（OSError 子类，先判）→"权限不足：…"，其余→"未预期的错误：…"。任务函数薄封装：逐个直接调操作层并返回其结果 dict（`classic_set_worker` 依据 enable 调 `enable_classic/disable_classic`；`restore_all_worker` 调 `store.restore_all`）。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: 4 passed（Module 契约 2 + 新增 2）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/workers.py tests/test_right_menu_ui.py
git commit -m "feat(right_menu): QThread 任务组与 worker 封装"
```

---

### Task 13: UI 基础（widgets 助手 + 表格工厂 + page 壳 + 扫描标签）

**Files:**
- Create: `modules/right_menu/widgets/__init__.py`
- Create: `modules/right_menu/widgets/tables.py`
- Create: `modules/right_menu/widgets/page_tabs/__init__.py`
- Create: `modules/right_menu/widgets/page_tabs/scan_tab.py`
- Create: `modules/right_menu/widgets/page.py`
- Modify: `modules/right_menu/module.py`（`create_page` 惰性 import 实装）
- Test: `tests/test_right_menu_ui.py`（追加）

**Interfaces:**
- Consumes: `ui/widgets.py` 工厂；`workers.TaskGroup/scan_scope_worker/apply_op_worker`（Task 12）；`scan.SCOPES/scan_scope`（Task 4）；`ops.apply_op`（Task 6）；`store.load`（Task 3）；`registry_backend.Win32Backend`（Task 2）。
- Produces: `widgets.confirm/notify/alert/make_card_block/card_qss/NOTIFY_MS`（镜像 proxy_ctrl）；`widgets.tables.make_table/fill_table/clear_table/fill_action_cell`；`widgets.page.RightMenuPage`（`frameless=True`；属性 `page.backend`、`page.scan`；`title_bar_spec`）；`widgets.page_tabs.scan_tab.ScanTab(owner, group, *, parent=None, page=None, backend=None)`（方法 `refresh()` / 属性 `table`、`combo_scope`、`edit_search`、`_filtered(rows)`）。

- [x] **Step 1: 写失败测试**（追加到 `tests/test_right_menu_ui.py`）

```python
def test_page_shell_contract(qapp):
    from modules.right_menu.widgets.page import RightMenuPage
    from modules.right_menu.module import Module
    from modules.right_menu.registry_backend import FakeRegistry
    class _Ctx:  # 最小上下文（不建真窗口）
        config = None; host_window = None; app = qapp; registry = None; tray = None
    m = Module(_Ctx())
    page = RightMenuPage(m, parent=None, backend=FakeRegistry())
    try:
        assert page.frameless is True
        assert page.tabs.count() == 5                      # 五标签
        spec = page.title_bar_spec
        assert spec["widgets"] is False and len(spec["buttons"]) == 2
        assert page.scan is not None
    finally:
        page.deleteLater(); qapp.processEvents()


def test_scan_tab_scope_combo_and_filter(qapp):
    from modules.right_menu.widgets.page_tabs.scan_tab import ScanTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    group = TaskGroup()
    tab = ScanTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        assert tab.combo_scope.count() == 4                # file/directory/background/drive
        rows = [{"display_name": "Alpha"}, {"display_name": "Beta"}]
        assert tab._filtered(rows)[0]["display_name"] == "Alpha"
        tab.edit_search.setText("bet")                     # 不区分大小写包含
        filtered = tab._filtered(rows)
        assert len(filtered) == 1 and filtered[0]["display_name"] == "Beta"
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()
```

（第二条测试断言过滤语义写死：搜索 `bet` → 只剩 Beta。表格行结构其余字段建行时可为空。）

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: FAIL（ModuleNotFoundError: modules.right_menu.widgets 等）

- [x] **Step 3: 实现**

1. `widgets/__init__.py`：**复制** `modules/proxy_ctrl/widgets/__init__.py` 的成熟实现（`card_qss/make_card_block/confirm/notify/alert/NOTIFY_MS/add_chip/reset_chips`；去掉 `make_usage_bar` 与 `_bar_qss`——本模块无进度条需求）。文件头注释改为 right_menu 语境。保持「不 import 同包兄弟模块」。
2. `widgets/tables.py`：**复制** `modules/proxy_ctrl/widgets/tables.py`（`table_qss/make_table/NumItem/fill_table/fill_action_cell/clear_table`；`columns/chips/actions` 语义完全一致，`min_height_key="log_table_min_height"`），文件头注释改 right_menu 语境。
3. `widgets/page_tabs/__init__.py`：`__all__ = ["ScanTab"]`，`from .scan_tab import ScanTab`（后续任务往 `__all__` 追加 ShellNewTab/ClassicTab/CustomTab/SettingsTab 并同步 import）。
4. `widgets/page_tabs/scan_tab.py`：`class ScanTab(QtWidgets.QWidget)`；构造参数 `(owner, group, *, parent=None, page=None, backend=None)`；`backend=None` 时惰性建 `Win32Backend()`（**测试注入 FakeRegistry**）。根布局：`make_card_block("扫描参数")` 内一行 = `combo_scope`（`make_combo([标题], parent=card)`，项来自 `SCOPES` 中文映射 `{"file":"文件","directory":"文件夹","background":"文件夹背景","drive":"驱动器"}`，`currentIndexChanged` → `refresh()`）+ `edit_search`（`make_line_edit("搜索名称或命令…")`，`textChanged` → 本地过滤重填表）+ `btn_refresh`（`make_button("刷新")`）；下接 `make_table(("名称","作用域","命令","来源","状态","操作"))`（`self.table`）；底部 `hint` label。扫描动作：`group.start(lambda ctx: scan_scope_worker(ctx, self._backend, scope_key), on_ok=self._apply_rows, ...)`；`on_busy` 时 `btn_refresh.setEnabled(False)`。行渲染 `fill_table`：命令截断 60 字符 + 全文 `setToolTip`（格式化函数 `(v,row)` 支持）；来源 `hive.upper()`；状态列 `chips={4: lambda row: ("已隐藏","warning") if row["disabled"] else ("显示","success")}`；操作列 `actions=[("隐藏", lambda row: row), ("恢复", ...)]`——**实现细节**：`fill_table` 的 `actions` 是 `[(text, build(row))]` 且统一一个 `action_handler`，故按「推入一行时根据 `disabled` 只放单个按钮」实现：`actions=[("恢复" if r["disabled"] else "隐藏", lambda row: row)]`（lambda 需默认参绑定，避免闭包晚绑定）。`action_handler(row)` → `group.start(lambda ctx: apply_op_worker(ctx, self._backend, {"action": "restore" if row["disabled"] else "disable", "hive": row["hive"], "key_path": row["key_path"], "name": row.get("name")}), on_ok=...)`；成功后 `notify` + `refresh()`。`_filtered(rows)` = `[r for r in rows if q in r["display_name"].casefold() or q in str(r.get("command") or "").casefold()]`（q 为空原样返回；不区分大小写）。
5. `widgets/page.py`：`class RightMenuPage(QtWidgets.QScrollArea)`，**构造 `(owner, parent=None, *, backend=None)`**；`frameless=True`；`self.backend = backend if backend is not None else Win32Backend()`（**先探 `if backend is None: from ..registry_backend import Win32Backend`** 保持惰性）；每个标签构造统一传 `backend=self.backend`（页面是 backend 的单一来源，标签一律 `backend=...` 必传 kwarg）。`self._group = TaskGroup(self)`；`_TABS = (("scan","右键项"), ("shellnew","新建菜单"), ("classic","经典菜单"), ("custom","自定义项"), ("settings","设置"))`；五个标签先全部建 `ScanTab`，其余四个本任务**占位**：`ShellNewTab/ClassicTab/CustomTab/SettingsTab` 尚未存在——**本任务只建 scan 真实现 + 其余四个用 `make_label("即将上线")` 的 `QtWidgets.QWidget` 占位**（后续任务逐个替换）；`title_bar_spec` property 返 `{"buttons":[{"icon":FluentIcon.SYNC,"text":"刷新","tooltip":"重新扫描当前标签数据","cb":self.refresh},{"icon":FluentIcon.FOLDER,"text":"数据目录","tooltip":"打开本模块数据目录","cb":self.open_data_dir}],"widgets":False}`；`refresh()` → `self.scan.refresh()`；`open_data_dir()` → `os.startfile(os.path.dirname(store.STATE_PATH))`（try/except `OSError/AttributeError` → `notify(error=True)`）；footer label + `_group.idle.connect(self._sync_enabled)` + `destroyed.connect(self._shutdown)` + `paintEvent` 用 `theme_palette()["bg_app"]` 填 viewport（复制 proxy_ctrl page.py 尾部 3 行）。
6. `module.py`：`create_page(self, parent)` → `from .widgets.page import RightMenuPage; return RightMenuPage(self, parent)`（函数内 import，保持顶层无 Qt）。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: 6 passed（原 4 + 新增 2）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/widgets modules/right_menu/module.py tests/test_right_menu_ui.py
git commit -m "feat(right_menu): 详情页骨架与扫描标签（UI 基础/表格/frameless）"
```

---

### Task 14: 首页小卡

**Files:**
- Create: `modules/right_menu/widgets/home_widget.py`
- Modify: `modules/right_menu/module.py`（`create_home_widget` + 定时器实装）
- Test: `tests/test_right_menu_ui.py`（追加）

**Interfaces:**
- Consumes: `store.load`；`classic.get_classic_state`（Task 7）；`workers.TaskGroup/classic_state_worker`（Task 12）；`ui.module_pages.open_module_page`。
- Produces: `HOME_INTERVAL_MS=30000`；`home_summary(state, classic_state)->dict`；`class RightMenuHomeWidget(owner, parent=None)`（`tick()` / `_render()` / `_stop()`）。

- [x] **Step 1: 写失败测试**（追加到 `tests/test_right_menu_ui.py`）

```python
def test_home_summary_counts(qapp, tmp_path, monkeypatch):
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.home_widget import home_summary
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    st = rm_store._empty_state()
    st["disabled"].append({"hive": "hkcu", "key_path": "k", "name": None, "original": None, "ts": "t"})
    st["custom_items"].append({"id": "1", "title": "T"})
    got = home_summary(st, "enabled")
    assert got == {"classic": "enabled", "disabled_count": 1, "custom_count": 1}


def test_home_widget_renders(qapp, tmp_path, monkeypatch):
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.home_widget import RightMenuHomeWidget
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    w = RightMenuHomeWidget(None, parent=None)
    try:
        w._render()
        assert w.chip.text()                 # 经典状态胶囊有文案
        w._stop()
    finally:
        w.deleteLater(); qapp.processEvents()
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: FAIL（ModuleNotFoundError: home_widget 或 home_summary 不存在）

- [x] **Step 3: 实现**

1. `home_widget.py`：`home_summary(state, classic_state)` → `{"classic": classic_state, "disabled_count": len(state.get("disabled") or []), "custom_count": len(state.get("custom_items") or [])}`（纯函数，测试直测）。
2. `class RightMenuHomeWidget(QtWidgets.QWidget)`：镜像 `ProxyHomeWidget` 结构（`TaskGroup(self)`、`setMinimumWidth(200)`、head= label「右键菜单」+ `make_tool_button("打开", kind="ghost", size="sm")` → `open_module_page(self._owner, self)`、`chip=make_status_chip("未读取", kind="info")`、两行 `_add_row("已隐藏", "—")`/`_add_row("自定义", "—")`、`destroyed.connect(self._stop)`、`_stop` 内 `self._group.shutdown()`）。`_render()`：`state=store.load()`；**读经典状态不走线程**（注册表读是毫秒级，为卡片渲染起线程不值）：`classic_state = classic.get_classic_state(self._classic_backend())`——`_classic_backend()` 惰性 `Win32Backend()`（**构造注入可测**：`__init__(owner, parent=None, *, backend=None, classic_getter=None)`，`classic_getter` 默认 `classic.get_classic_state`，测试可替换成 `lambda be: "enabled"`）。chip 文案映射 `{"enabled":"经典菜单","disabled":"新版菜单","unknown":"未知状态"}`，kind `{"enabled":"warning","disabled":"success","unknown":"info"}`（`make_status_chip` 的 kind 用图文风格 kind，取 `success/warning/info` 三态）。`tick()`：`HOME_INTERVAL_MS=30000` 由 Module 定时器驱动；`tick` 无网络无子进程，直接 `_render()` 返回 True（**不做线程**——本卡数据全是本地注册表/文件读，proxy 卡用线程是因为要起 git 子进程）。
3. `module.py`：`create_home_widget(self, parent)` → `from .widgets.home_widget import HOME_INTERVAL_MS, RightMenuHomeWidget; widget = RightMenuHomeWidget(self, parent); widget.destroyed.connect(self._on_home_destroyed); self._home_widget = widget; self._refresh_home(); return widget`；`start()` 建 `QTimer` interval=`HOME_INTERVAL_MS` → `self._home_tick()`（widget 为 None 直接返回；`tick()` 抛 `RuntimeError` → `self._home_widget=None`）；`stop()` 停表 + 置 None；`_refresh_home` 镜像 proxy_ctrl（`widget._render()` + RuntimeError 兜底）。`__init__` 已存 `_home_timer/_home_widget`（Task 1 已建）。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: 8 passed（原 6 + 新增 2）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/widgets/home_widget.py modules/right_menu/module.py tests/test_right_menu_ui.py
git commit -m "feat(right_menu): 首页小卡（经典状态/计数/定时刷新）"
```

---

### Task 15: 新建菜单标签（ShellNew）

**Files:**
- Create: `modules/right_menu/widgets/page_tabs/shellnew_tab.py`
- Modify: `modules/right_menu/widgets/page_tabs/__init__.py`（导出 ShellNewTab）
- Modify: `modules/right_menu/widgets/page.py`（替换占位标签）
- Test: `tests/test_right_menu_ui.py`（追加）

**Interfaces:**
- Consumes: `shellnew.scan_shellnew/hide_shellnew/restore_shellnew/delete_shellnew/create_shellnew`（Task 8）；`workers.scan_shellnew_worker`（Task 12）；`widgets.confirm/notify`。
- Produces: `class ShellNewTab(owner, group, *, parent=None, page=None, backend=None)`（方法 `refresh()`、属性 `table`）。

- [x] **Step 1: 写失败测试**（追加到 `tests/test_right_menu_ui.py`）

```python
def test_shellnew_tab_renders_rows(qapp):
    from modules.right_menu.widgets.page_tabs.shellnew_tab import ShellNewTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    r = FakeRegistry()
    r.set("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile", "")
    group = TaskGroup()
    tab = ShellNewTab(None, group, parent=None, page=None, backend=r)
    try:
        tab._apply_rows([{"hive": "hkcu", "ext": ".xyz", "kind": "null", "hidden": False,
                          "key_path": r"Software\Classes\.xyz\ShellNew", "template": None,
                          "values": {"NullFile": ""}}])
        assert tab.table.rowCount() == 1
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: FAIL（ModuleNotFoundError: shellnew_tab）

- [x] **Step 3: 实现**

1. `shellnew_tab.py`：`ScanTab` 同构（`make_card_block("新建菜单")` 参数行：`btn_refresh=make_button("刷新")` + `btn_add=make_button("新增模板", kind="primary")`；表格 `make_table(("扩展名","类型","模板","状态","操作"))`；类型 chip：`null→"空文件"(info)`、`template→"模板"(success)`、`data→"数据"(info)`、`command→"命令"(warning)`、`unknown→"未知"(error)`；状态 chip = 隐藏/显示；操作列同 scan_tab 的单按钮模式：隐藏/恢复/删除（HKCU 才给删除）——`actions` build 逻辑：`disabled`→["恢复"]；隐藏不可用→["隐藏"] + （`hive=="hkcu"`）["删除"]，实现上按 `fill_action_cell` 直接铺多按钮（**不用 `fill_table` 的 actions 参数**，因为按钮组每行不同——用 `fill_table` 渲染文本列后，对操作列逐行手调 `fill_action_cell(table, r, c, [(t,arg),...], handler)` 即可）。`隐藏/恢复` 走 `apply` 直接调 `shellnew.hide_shellnew/restore_shellnew`（本地注册表操作毫秒级，**不起线程**；HKLM 内部自会走提权阻塞——这里要起线程，统一都进线程更安全：用 `group.start(lambda ctx: ...)` 包装）。删除先 `confirm`。`btn_add` → `_add_dialog()`：`QDialog` 内 `make_line_edit("扩展名，如 .md")` + `make_combo(["空文件","模板文件"])` + 模板路径 `make_line_edit` + 文件选择按钮（`QFileDialog.getOpenFileName`）；确认后 `create_shellnew(backend, ext, name=None, kind=...)` 走线程 + notify。
2. `page_tabs/__init__.py`：追加 `from .shellnew_tab import ShellNewTab`。
3. `page.py`：五个标签全部改为真实现类（如 `ShellNewTab(owner, self._group, parent=self.tabs, page=self, backend=self.backend)`——**页面的 `self.backend` 是唯一来源，标签构造一律 `backend=self.backend`**），`_TABS` 映射：`("shellnew","新建菜单")` 对应 attrs。**注意**：custom/settings 的类此时还不存在——本任务把 custom/settings 仍留占位（`QWidget+label`），classic 在 T16、custom 在 T17、settings 在 T18 逐个接真实现。page.py 中通过一个小助手 `_make_placeholder(text)` 生成占位。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: 9 passed（原 8 + 新增 1）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/widgets tests/test_right_menu_ui.py
git commit -m "feat(right_menu): 新建菜单标签（ShellNew 管理）"
```

---

### Task 16: 经典菜单标签

**Files:**
- Create: `modules/right_menu/widgets/page_tabs/classic_tab.py`
- Modify: `modules/right_menu/widgets/page_tabs/__init__.py`
- Modify: `modules/right_menu/widgets/page.py`
- Test: `tests/test_right_menu_ui.py`（追加）

**Interfaces:**
- Consumes: `classic.get_classic_state/enable_classic/disable_classic/restart_explorer`（Task 7）；`workers.classic_state_worker/classic_set_worker`（Task 12）；`widgets.confirm/notify`。
- Produces: `class ClassicTab(owner, group, *, parent=None, page=None, backend=None)`（方法 `refresh()`、`toggle()`、`restart_explorer()`；属性 `chip`、`btn_toggle`、`btn_restart`）。

- [x] **Step 1: 写失败测试**（追加到 `tests/test_right_menu_ui.py`）

```python
def test_classic_tab_toggle_roundtrip(qapp):
    from modules.right_menu.widgets.page_tabs.classic_tab import ClassicTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu import classic
    r = FakeRegistry()
    group = TaskGroup()
    tab = ClassicTab(None, group, parent=None, page=None, backend=r)
    try:
        assert classic.get_classic_state(r) == "disabled"
        ok = tab.toggle(confirm_fn=lambda *a, **k: True)   # 绕开模态确认
        deadline = __import__("time").time() + 5
        while group.busy and __import__("time").time() < deadline:
            qapp.processEvents()
        assert ok and classic.get_classic_state(r) == "enabled"
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()
```

（`toggle` 接受 `confirm_fn` 注入——缺省 `widgets.confirm(self, ...)`。模态确认在离屏测试里会挂起，所以**所有会弹 confirm 的公开方法都要开 `confirm_fn` 注入缝**，T15/T17/T18 同规。）

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: FAIL（ModuleNotFoundError: classic_tab）

- [x] **Step 3: 实现**

1. `classic_tab.py`：「经典菜单」卡（`make_card_block`）内：状态行 = `make_label("当前风格")` + `self.chip`（三态映射同 home_widget）+ `btn_toggle=make_button("切换到经典菜单", kind="primary")`；说明 label（切换需重启资源管理器生效；「重启资源管理器」会关闭所有资源管理器窗口）；`btn_restart=make_button("重启资源管理器", kind="danger")`。`refresh()`：`group.start(classic_state_worker, ...)` 或直接读（**读无害且毫秒级——直接同步读**：`classic.get_classic_state(self._backend)`；写才进线程）。`toggle(*, confirm_fn=None)`：`state = classic.get_classic_state(self._backend)`；`enable = (state != "enabled")`（enabled→关；disabled/unknown→开）；`confirm_fn or (lambda *a, **k: confirm(self, "切换经典菜单", "将切换 Windows 11 右键菜单为经典样式（或还原为新版样式），重启资源管理器后生效。是否继续？", ok_text="切换"))`；确认→`group.start(lambda ctx: classic_set_worker(ctx, self._backend, enable=enable), on_ok=...)`；成功 `notify("已切换","重启资源管理器后生效")` + `refresh()`。`restart_explorer(*, confirm_fn=None)`：确认文案强调「将强制结束并重启资源管理器」→ `group.start(lambda ctx: classic.restart_explorer(), ...)`（restart_explorer 毫秒级起 cmd）。
2. `page_tabs/__init__.py` 追加导出；`page.py` 替换 classic 占位为真实现。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: 10 passed（原 9 + 新增 1）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/widgets tests/test_right_menu_ui.py
git commit -m "feat(right_menu): 经典菜单标签（状态/切换/重启资源管理器）"
```

---

### Task 17: 自定义项标签 + 编辑器对话框

**Files:**
- Create: `modules/right_menu/widgets/editor_dialog.py`
- Create: `modules/right_menu/widgets/page_tabs/custom_tab.py`
- Modify: `modules/right_menu/widgets/page_tabs/__init__.py`
- Modify: `modules/right_menu/widgets/page.py`
- Test: `tests/test_right_menu_ui.py`（追加）

**Interfaces:**
- Consumes: `custom.validate_item/save_item/delete_item/export_items/import_items/get_custom_items 等价（store.get_custom_items/set_custom_items）`（Task 9）；`workers.save_item_worker/delete_item_worker`（Task 12）。
- Produces: `class CustomItemDialog(parent, *, item=None)`（`item` 为 None=新建；方法 `value()` → DOM dict；确定按钮校验 `validate_item`，errors 非空则 `notify(error=True)` 不放行）；`class CustomTab(owner, group, *, parent=None, page=None, backend=None)`（方法 `refresh()`、`add_item()`、`edit_item(item_id)`、`delete_item(item_id, *, confirm_fn=None)`、`move(item_id, delta)`、`export_items(*, path=None)`、`import_items(*, path=None)`；属性 `table`）。

- [x] **Step 1: 写失败测试**（追加到 `tests/test_right_menu_ui.py`）

```python
def test_editor_dialog_value_roundtrip(qapp):
    from modules.right_menu.custom import validate_item
    from modules.right_menu.widgets.editor_dialog import CustomItemDialog
    item = {"id": "abc123", "title": "用 VSCode 打开", "icon": "", "scope": "file",
            "ext_filter": [".py", ".md"], "hive": "hkcu", "extended": False,
            "position": "default", "action": {"kind": "program", "target": r"C:\vscode.exe",
            "args": '"%1"', "workdir": ""}, "children": []}
    dlg = CustomItemDialog(None, item=item)
    try:
        dom = dlg.value()
        assert dom["title"] == "用 VSCode 打开" and dom["ext_filter"] == [".py", ".md"]
        assert dom["action"]["target"].endswith("vscode.exe")
        out = validate_item(dom)
        assert out["ok"] and not out["errors"]
    finally:
        dlg.deleteLater(); qapp.processEvents()


def test_custom_tab_move_persists(qapp, tmp_path, monkeypatch):
    from modules.right_menu import store as rm_store
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu.widgets.page_tabs.custom_tab import CustomTab
    from modules.right_menu.workers import TaskGroup
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(rm_store, "BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(rm_store, "TEMPLATES_DIR", str(tmp_path / "tp"))
    a = {"id": "a1", "title": "A", "scope": "file", "ext_filter": [],
         "action": {"kind": "program", "target": "x", "args": "", "workdir": ""},
         "children": [], "icon": "", "hive": "hkcu", "extended": False, "position": "default"}
    b = dict(a, id="b2", title="B")
    rm_store.set_custom_items([a, b])
    group = TaskGroup()
    tab = CustomTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        assert tab.move("b2", -1) is True                     # 上移
        ids = [i["id"] for i in rm_store.get_custom_items()]
        assert ids == ["b2", "a1"]
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()
```

（DOM 契约以 Task 9 为准确认：`ext_filter` 是**列表**；`action.kind` 取 `"program"|"open"`；`validate_item` 返回 dict `{"ok","errors","warnings"}`。编辑器把扩展名输入框文本「py,md」规范化为 `[".py", ".md"]`。）

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: FAIL（ModuleNotFoundError: editor_dialog / custom_tab）

- [x] **Step 3: 实现**

1. `editor_dialog.py`：`QDialog` 子类（**不用 QMessageBox 系**）；表单：标题 `make_line_edit`、图标 `make_line_edit("图标路径（可选）")`、作用域 `make_combo(["文件","文件夹","文件夹背景","驱动器"])`、扩展名过滤 `make_line_edit("如 py,md，留空=全部")`、命令类型 `make_combo(["运行命令","打开路径/URL"])`（→ `value()` 映射 `kind="program"|"open"`）、目标 `make_line_edit("程序/命令/URL")`、参数 `make_line_edit('如 "%1"，支持 %1/%*/%V')`、工作目录 `make_line_edit`、`make_checkbox("仅按住 Shift 时显示")`、位置 `make_combo(["默认","顶部","底部"])`；子菜单编辑区：`QTreeWidget`（2 列：标题/目标）+ 按钮「加子项」「删子项」（子项仅标题+目标+参数，嵌套一层；树仅 1 层，`validate_item` 允许 children 递归但 UI 只做 1 层——**不做无限嵌套 UI**，递归结构由文件导入支持）。`value()` 逆映射回 DOM（中文标签→英文枚举值；扩展名输入「py, md」→ `[".py", ".md"]`（去空白、无前缀补 `.`）；`position` 默认→`"default"`；子项→children 列表）；`accept()` 前校验：`validate_item(dom)` 的 `errors` 非空 → `notify` 不放行，`warnings` 非空 → 仍然 `notify(warning)` 但**不阻断**（用户可确认继续——简化：警告直接显示并放行）。
2. `custom_tab.py`：参数行（「新建项」「导入」「导出」按钮 + 刷新）；表格 `make_table(("顺序","标题","作用域","扩展名","命令","操作"))`；操作列逐行 `fill_action_cell`（「编辑」「删除」「上移」「下移」四个 `make_tool_button(size="sm")`）。`move(item_id, delta)`：读 `store.get_custom_items()`→列表内 index 调整（越界返 False；成功 `set_custom_items` + 刷新 + **可选**重投影：直接调 `custom.sync_all(backend)` 保持注册表与顺序一致——顺序不写进注册表（无顺序语义），**只存账本**，注册表投影与顺序无关，sync_all 不必在 move 里跑）。`add_item()` → `CustomItemDialog(self)` → `dom` → `group.start(lambda ctx: save_item_worker(ctx, self._backend, dom), on_ok=...)`。`edit_item(item_id)`：从 `store.get_custom_items()` 找 item → 对话框 → 保存。`delete_item`：`confirm_fn` 注入 → `delete_item_worker`。`export_items(*, path=None)`：`path or QFileDialog.getSaveFileName(...)[0]` → `custom.export_items(path)`；`import_items`：选文件 → `custom.import_items(self._backend, path)` → 刷新。
3. `page_tabs/__init__.py` 追加；`page.py` 替换 custom 占位。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: 12 passed（原 10 + 新增 2）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/widgets tests/test_right_menu_ui.py
git commit -m "feat(right_menu): 自定义项标签与编辑器（子菜单树/导入导出）"
```

---

### Task 18: 设置标签（YZplan 子菜单/一键还原/备份）

**Files:**
- Create: `modules/right_menu/widgets/restore_dialog.py`
- Create: `modules/right_menu/widgets/page_tabs/settings_tab.py`
- Modify: `modules/right_menu/widgets/page_tabs/__init__.py`
- Modify: `modules/right_menu/widgets/page.py`
- Test: `tests/test_right_menu_ui.py`（追加）

**Interfaces:**
- Consumes: `yzmenu.install_yzmenu/uninstall_yzmenu/get_yzmenu_state/ACTIONS/ACTION_LABELS`（Task 10）；`store.restore_all/load/backup_snapshot`（Task 3/11）；`workers.yzmenu_state_worker/yzmenu_install_worker/restore_all_worker`（Task 12）。
- Produces: `class RestoreDialog(parent)`（预览将撤销的条目列表；确认按钮文案「还原」）；`class SettingsTab(owner, group, *, parent=None, page=None, backend=None)`（方法 `refresh()`、`export_backup()`、`open_data_dir()`；属性 `check_yzmenu`、`list_actions`（`QListWidget` 或复选框容器）、`btn_restore`、`table_backups`）。

- [x] **Step 1: 写失败测试**（追加到 `tests/test_right_menu_ui.py`）

```python
def test_settings_tab_restore_all_roundtrip(qapp, tmp_path, monkeypatch):
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.page_tabs.settings_tab import SettingsTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(rm_store, "BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(rm_store, "TEMPLATES_DIR", str(tmp_path / "tp"))
    r = FakeRegistry()
    r.set("hkcu", r"Software\Classes\*\shell\X", "", "X")
    rm_store.add_disabled("hkcu", r"Software\Classes\*\shell\X", None)
    r.set("hkcu", r"Software\Classes\*\shell\X", "LegacyDisable", "")
    group = TaskGroup()
    tab = SettingsTab(None, group, parent=None, page=None, backend=r)
    try:
        ok = tab.restore_all(confirm_fn=lambda *a, **k: True)
        deadline = __import__("time").time() + 5
        while group.busy and __import__("time").time() < deadline:
            qapp.processEvents()
        assert ok and r.get("hkcu", r"Software\Classes\*\shell\X", "LegacyDisable") is None
        assert rm_store.load()["disabled"] == []
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: FAIL（ModuleNotFoundError: settings_tab）

- [x] **Step 3: 实现**

1. `settings_tab.py`：「YZplan 右键」卡：`check_yzmenu=make_checkbox("在系统右键显示 YZplan 子菜单")`（勾选/取消 → `yzmenu_install_worker`（actions=当前多选）或卸载；`_sync_enabled` 期间禁用防抖动）；动作多选区：每个 `ACTIONS` 一项 `make_checkbox(ACTION_LABELS[a])`（默认全选），「应用动作」按钮单独提交（避免勾一下装一次）。「一键还原」卡：说明 label（将撤销本模块全部改动：隐藏项/ShellNew/自定义项/YZplan 菜单/经典菜单）+ `btn_restore=make_button("一键还原", kind="danger")` → `RestoreDialog` 预览 → 确认 → `restore_all_worker` → 结果 `notify`（报告行数）→ `refresh()`。「备份」卡：`table_backups=make_table(("时间","原因","操作"))`（行= `os.listdir(store.BACKUP_DIR)` 的 *.json；「打开」按钮 `os.startfile` 该文件所在目录——**不做恢复单份备份**，一期只读浏览）。「数据目录」行按钮（同 page.open_data_dir 逻辑，复用 `page.open_data_dir` 若可，直接再实现一次 3 行）。
2. `restore_dialog.py`：`QDialog`；label 列出将撤销条目（读 `store.load()`：disabled/shellnew_hidden/custom_items/yzmenu 计数 + 经典菜单状态）+ 「还原」「取消」按钮；`exec()` 返回 Accepted 与否。
3. `page.py` 拼接（五标签全真实现，`_TABS` 对应 attr：`scan/shellnew/classic/custom/settings`）；`page_tabs/__init__.py` 补全导出。
4. **注意**：SettingsTab 渲染备份表时 `os.listdir` 需 try/except（目录可能不存在）。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py -v`
Expected: 13 passed（原 12 + 新增 1）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/widgets tests/test_right_menu_ui.py
git commit -m "feat(right_menu): 设置标签（YZplan 子菜单/一键还原/备份）"
```

---

### Task 19: 模块动作分发 + 主程序接入

**Files:**
- Modify: `modules/right_menu/module.py`（`dispatch_menu_action` 实装 + `start()` 消费 `pending_menu_action`）
- Modify: `main.py`（单实例分支 `--menu-action` 转发；`context.pending_menu_action`）
- Modify: `core/tray/mcp.py`（dispatch 加 `menu_action` + `_mcp_menu_action`）
- Test: `tests/test_right_menu_ui.py`（追加）；`tests/test_mcp_tray.py`（追加）

**Interfaces:**
- Consumes: `elevate.menu_action_command/forward_menu_action`（Task 5）；`classic.*`；`store.restore_all`；`ui.module_pages.open_module_page`。
- Produces: `Module.dispatch_menu_action(action)->bool`（open_manager/toggle_classic/show_window/restore_all；未知 action 返 False）；`Tray._mcp_menu_action(action)`。

- [x] **Step 1: 写失败测试**

```python
# 追加到 tests/test_right_menu_ui.py
def test_dispatch_menu_action_unknown_returns_false(qapp):
    from modules.right_menu.module import Module
    class _Ctx:
        config = None; host_window = None; app = qapp; registry = None; tray = None
    m = Module(_Ctx())
    assert m.dispatch_menu_action("nope") is False


def test_dispatch_open_manager(qapp, monkeypatch):
    import modules.right_menu.module as rm
    calls = []
    monkeypatch.setattr("ui.module_pages.open_module_page", lambda mod, *a, **k: calls.append(mod))
    from modules.right_menu.module import Module
    class _Ctx:
        config = None; host_window = None; app = qapp; registry = None; tray = None
    m = Module(_Ctx())
    assert m.dispatch_menu_action("open_manager") is True
    assert calls and calls[0] is m
```

```python
# 追加到 tests/test_mcp_tray.py（沿用该文件既有 _make_tray/_dispatch 模式）
def test_menu_action_dispatches_to_module(monkeypatch):
    tray = _make_tray()
    class _Mod:
        def dispatch_menu_action(self, action): self.action = action; return True
    mod = _Mod()
    class _Reg:
        def get(self, mid): return mod if mid == "right_menu" else None
    class _Ctx:
        registry = _Reg()
    tray._context = _Ctx()
    _dispatch(tray, "menu_action", action="open_manager")
    assert mod.action == "open_manager"
```

（`_make_tray/_dispatch` 为该文件既有助手；若命名差异以该文件现状为准。）

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_ui.py tests/test_mcp_tray.py -v`
Expected: FAIL（dispatch_menu_action 占位返回 None / menu_action 不在 dispatch）

- [x] **Step 3: 实现**

1. `module.py::dispatch_menu_action(action)`：
   - `"open_manager"`→`from ui.module_pages import open_module_page; open_module_page(self)`→True；
   - `"toggle_classic"`→`from .registry_backend import Win32Backend; from .classic import get_classic_state, enable_classic, disable_classic; be=Win32Backend(); enable = get_classic_state(be) != "enabled"; (enable_classic(be) if enable else disable_classic(be))["ok"]`（**注意**：启用时若已是 unknown，按「设为经典」处理）；
   - `"show_window"`→`win = getattr(self.context, "host_window", None)`；`win.window if hasattr(win,"window") else win` → showNormal/raise_/activateWindow → True（无窗口返 False）；
   - `"restore_all"`→`from .registry_backend import Win32Backend; from .store import restore_all; return bool(restore_all(Win32Backend())["ok"])`；
   - 其余 → False。全部包 try/except→False（菜单动作必须静默稳）。
2. `main.py` 单实例分支（L44-67 块内，183 分支处）：在 `os._exit(0)` 前插入：
   ```python
   if "--menu-action" in sys.argv:
       try:
           _i = sys.argv.index("--menu-action")
           _action = sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ""
           if _action:
               from modules.right_menu.elevate import forward_menu_action as _fwd
               _fwd(_action)
       except Exception:
           pass
   ```
   （保持 `os._exit(0)` 不变——已有实例收到 inbox 命令后退出本进程。）
3. `main.py` main()：L212-214 `context` 创建后设 `context.pending_menu_action = _pending_action`（顶部解析：`_pending_action = None; if "--menu-action" in sys.argv: ...`——**仅在非互斥退出路径能跑到这里**，即首实例携带该参数）。
4. `module.py::start()`：`super().start()` 后：`action = getattr(self.context, "pending_menu_action", None)`；非空 → `QtCore.QTimer.singleShot(0, lambda: self.dispatch_menu_action(action))` + `self.context.pending_menu_action = None`（防重复消费）。**`start()` 已有 Qt 依赖**（module.py 在 registry 加载时被 import；它已在 Qt 环境内，不受早退通道纪律约束——早退通道只约束 import 链上不触 Qt 的 `elevate`）。
5. `core/tray/mcp.py`：dispatch dict 加 `"menu_action": lambda: self._mcp_menu_action(payload.get("action"))`；新方法：
   ```python
   def _mcp_menu_action(self, action):
       try:
           if not action or not self._context or not hasattr(self._context, "registry"):
               return
           mod = self._context.registry.get("right_menu")
           if mod is not None and hasattr(mod, "dispatch_menu_action"):
               mod.dispatch_menu_action(str(action))
       except Exception:
           pass
   ```

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_ui.py tests/test_mcp_tray.py -v`
Expected: 全部通过（ui 15 + tray 原数 + 1）

- [x] **Step 5: Commit**

```bash
git add modules/right_menu/module.py main.py core/tray/mcp.py tests/test_right_menu_ui.py tests/test_mcp_tray.py
git commit -m "feat(right_menu): 菜单动作分发与主程序接入（--menu-action/单实例/MCP）"
```

---

### Task 20: MCP 工具切片

**Files:**
- Create: `mcp_server/tools_right_menu.py`
- Modify: `mcp_server/__init__.py`（import + TOOLS 拼接）
- Test: `tests/test_right_menu_mcp.py`

**Interfaces:**
- Consumes: `registry_backend.Win32Backend`；`scan.scan_scope`；`ops.apply_op`；`shellnew.*`；`classic.*`；`store.*`；`custom.*`；`yzmenu.*`；`mcp_server.tools_system_config_gui._mcp_inbox_command`。
- Produces: `TOOLS` 列表（12 个工具：`right_menu_scan/set_disabled/classic_state/classic_set/custom_list/custom_save/custom_delete/shellnew_scan/shellnew_hide/shellnew_restore/restore_all/open_manager`）；`mcp_server.__init__` 的 `TOOLS` 包含上述。

- [x] **Step 1: 写失败测试**

```python
# tests/test_right_menu_mcp.py
from mcp_server import tools_right_menu as t


def test_tool_names_registered():
    from mcp_server import _TOOL_BY_NAME
    names = {x["name"] for x in t.TOOLS}
    assert {"right_menu_scan", "right_menu_set_disabled", "right_menu_classic_state",
            "right_menu_classic_set", "right_menu_custom_list", "right_menu_restore_all",
            "right_menu_open_manager"} <= names
    assert all(n in _TOOL_BY_NAME for n in names)


def test_scan_handler_uses_fake(monkeypatch):
    from modules.right_menu.registry_backend import FakeRegistry
    r = FakeRegistry()
    r.set("hkcu", r"Software\Classes\*\shell\Alpha", "", "Alpha")
    monkeypatch.setattr(t, "_backend", lambda: r)
    out = t.right_menu_scan({"scope": "file"})
    assert out["ok"] and out["items"][0]["display_name"] == "Alpha"


def test_hklm_write_returns_gui_hint(monkeypatch):
    out = t.right_menu_set_disabled({"action": "disable", "hive": "hklm",
                                     "key_path": r"Software\Classes\*\shell\X"})
    assert out["ok"] is False and "GUI" in out["error"]


def test_open_manager_queues_inbox(monkeypatch, tmp_path):
    monkeypatch.setattr(t, "DATA_DIR", str(tmp_path))
    out = t.right_menu_open_manager({})
    assert out["queued"] is True
```

- [x] **Step 2: 运行验证失败**

Run: `python -m pytest tests/test_right_menu_mcp.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 实现**

1. `tools_right_menu.py`：模块级 `from core.constants import DATA_DIR`（**函数内读模块全局**，便于测试 monkeypatch `t.DATA_DIR`）；`_backend()` 返回 `Win32Backend()`（monkeypatch 注入口）；每个工具函数返回 JSON 安全 dict（`{"ok":bool,...}`）；**HKLM 写**（set_disabled/classic? classic 是 HKCU/restore_all 内 HKLM 属提权范畴）→ 返回 `{"ok":False,"error":"HKLM 操作需通过 GUI（提权流程），请在 YZplan 窗口中执行"}`；`right_menu_scan`：`scope=="all"` 时四作用域合并，另附 `shellnew` 列表；`right_menu_open_manager`：调本地助手 `_queue_menu_action("open_manager")` —— **不用 `tools_system_config_gui._mcp_inbox_command`**（其写死 `core.constants.DATA_DIR`，测试无法经 `t.DATA_DIR` 隔离；且它 `silent=True` 弹托盘行为与本工具一致）。`_queue_menu_action(action)` 实现：`inbox=os.path.join(DATA_DIR,"mcp_inbox"); os.makedirs(...); payload={"id":uuid4().hex,"command":"menu_action","action":action,"time":...,"silent":True}`；写 `<id>.json`；返回 `{"queued":True,"command":"menu_action","inbox_file":path}`。`classic_set`：`enable` bool 参数→enable_classic/disable_classic；`custom_save`：入参 `item` dict → `custom.save_item(backend, item)`（**含注册表投影**：MCP 进程内投影 HKCU 可直写）；`custom_delete`：`item_id`→`custom.delete_item`；`shellnew_hide/restore`：入参 `hive/ext`→ 从 `scan_shellnew` 找匹配项再调（按 Task 8 签名传 item dict）；`restore_all`：`store.restore_all(_backend())`。
2. 各工具 `inputSchema` 按 spec §10 列写；**TOOLS 顺序**：拼接进 `mcp_server/__init__.py` TOOLS 时放最后（`+ tools_right_menu.TOOLS`）并 import。
3. **GUI 双写冲突**注意（spec §10）：MCP 写 store 前也调 `store.backup_snapshot`（restore_all/custom_save 内已含备份；直接写 store 的入口即这些）。`_TOOL_BY_NAME` 自动从 TOOLS 构建（检查 `mcp_server/__init__.py` 现状，若 `_TOOL_BY_NAME = {t["name"]: t for t in TOOLS}` 则无需改）。

- [x] **Step 4: 运行验证通过**

Run: `python -m pytest tests/test_right_menu_mcp.py -v`
Expected: 4 passed

- [x] **Step 5: Commit**

```bash
git add mcp_server/tools_right_menu.py mcp_server/__init__.py tests/test_right_menu_mcp.py
git commit -m "feat(right_menu): MCP 工具切片（扫描/开关/ShellNew/自定义/还原）"
```

---

### Task 21: CI 登记与全量验收

**Files:**
- Modify: `.github/workflows/python-app.yml`（4 个 chunk 登记新测试文件）
- Test: 全量

**Interfaces:**
- Consumes: 全部。

- [x] **Step 1: 登记 CI chunk**

将 10 个新测试文件按 chunk 均衡分配（现有 chunk 含 test_proxy_* 等；新增：）
- chunk1 += `tests/test_right_menu_scan.py tests/test_right_menu_store.py`
- chunk2 += `tests/test_right_menu_ops.py tests/test_right_menu_shellnew.py`
- chunk3 += `tests/test_right_menu_classic.py tests/test_right_menu_custom.py tests/test_right_menu_yzmenu.py`
- chunk4 += `tests/test_right_menu_elevate.py tests/test_right_menu_ui.py tests/test_right_menu_mcp.py`
（若 chunk 负载差异大，可自行微调——规则：**每个新文件恰好进一个 chunk**。）

- [x] **Step 2: 样式合规检查**

Run: `python scripts/audit_styles.py --check`
Expected: 无新增违规（exit 0）

Run: `python -m pytest tests/test_style_guardrails.py -v`
Expected: 全部通过（主题切换无残留、1.6x 无截断）

- [x] **Step 3: 全量测试**

Run: `python -m pytest tests/ -x -q`
Expected: 全部通过（含既有 + 新增 ~60 条）

- [ ] **Step 4: 实机验收清单（人工，对照 spec §13 一期）** — 待用户实机执行，清单与结果见 `.superpowers/sdd/2026-10-05-right-menu-manager/task-21-report.md`

1. 启动 YZplan → 打开「右键菜单」→「右键项」标签扫描：四作用域条目出现，结果与 regedit 抽查一致；
2. 隐藏一个 HKCU 项 → 资源管理器右键确认消失 → 恢复 → 出现（含 Shift 项 Extended 行为）；
3. HKLM 项点隐藏 → 弹 UAC（点否 → 界面提示「已取消」；点是 → 生效）；
4. 「新建菜单」隐藏 .txt 的 ShellNew → 桌面右键「新建」里消失 → 恢复；
5. 「经典菜单」切换 → 重启资源管理器 → 右键样式变化 → 切回；
6. 「自定义项」新建一个带 `%1` 的命令 → file 作用域 → 资源管理器选中文件右键出现该命令且执行正确；
7. 「设置」安装 YZplan 子菜单 → 桌面/文件夹/文件右键均出现 YZplan 子菜单 → 点「打开管理器」拉起窗口 → 卸载后消失；
8. 「一键还原」→ 全部改动消失（reg export 快照比对无残留）。

- [x] **Step 5: 更新计划文档勾选状态并 Commit**

```bash
git add .github/workflows/python-app.yml docs/superpowers/plans/2026-10-05-right-menu-manager.md
git commit -m "chore(right_menu): CI 登记与一期验收收尾"
```

---

## 附：任务依赖图

```
T1 ─┬─ T2 ─┬─ T3 ─┬─ T4 ──┐
    │      │      ├─ T5 ──┤
    │      │      ├─ T6 ──┤
    │      │      ├─ T7 ──┤
    │      │      └─ T8 ──┤
    │      └─ T9 ─────────┤
    │         T10 ────────┤
    │         T11 ────────┤
    └─ T12 ───────────────┼─ T13 ─ T14 ─ T15 ─ T16 ─ T17 ─ T18 ─ T19 ─ T20 ─ T21
```

（T11 依赖 T7/T9/T10；T13 依赖 T4/T6/T12 与 T2/T3。）



