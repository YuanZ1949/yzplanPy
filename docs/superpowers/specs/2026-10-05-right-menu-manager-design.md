# 右键菜单管理模块（right_menu）设计规格

- 日期：2026-10-05
- 形态：YZplan 新模块 `modules/right_menu/`，独立可开关，含二期原生组件 `native/win11_ctx/`
- 需求来源：用户 m0008「管理 Windows 右键的选项：桌面右键、文件右键、新建文件右键、Win11 以前的右键菜单选项到新文件右键」
- 已定决策（用户确认）：自建完整栈（自研 COM DLL + MSIX 稀疏包，不用第三方）；二期 DLL 用 **Rust (windows-rs)**；支持 UAC 提权修改 HKLM；功能全部要、分阶段；暴露 MCP 工具

## 1. 目标与非目标

### 目标

管理 Windows 资源管理器右键菜单的全生命周期，按里程碑交付：

1. **M1 只读扫描**——枚举文件/文件夹/桌面背景/驱动器右键项与「新建」菜单（ShellNew）项，展示名称/图标/命令/来源。
2. **M2 开关已有项**——对扫描到的项做隐藏/恢复（`LegacyDisable` 机制），支持 HKCU（直写）与 HKLM（UAC 提权作业）。
3. **M3 经典菜单总开关**——一键把 Win11 右键菜单切回 Win10 经典样式，撤销即还原；含「重启资源管理器」操作。
4. **M4 新建菜单管理**——ShellNew 项的隐藏/恢复；新增自定义模板（空文件/模板文件绑定）。
5. **M5 自定义右键项**——运行命令/程序、打开 URL/文件、多级子菜单、按扩展名/条件限定（含 Extended 仅 Shift 显示）；目标域 HKCU 默认、HKLM 可选（提权）。
6. **M6 YZplan 系统右键菜单**——在系统右键（文件/文件夹/桌面背景）加「YZplan」级联子菜单：快捷动作（打开管理器、切换经典菜单、显示主窗口等）+ 打开管理器入口；经单实例 IPC 唤起已运行的 YZplan。
7. **M7 MCP 切片**——`mcp_server/tools_right_menu.py`，只读直连 + HKCU 写直连 + HKLM 写经 GUI 提权。
8. **M8 二期：Win11 新菜单注入**——Rust `IExplorerCommand` DLL + MSIX 稀疏包，把经典项与自定义项渲染进 Win11 新版右键菜单；渲染源为 `win11.json`。

### 非目标（本期边界）

- 不管理 SendTo（发送到）菜单。
- 不修改文件关联（不写 `HKCU\Software\Classes\.ext` 的默认 ProgID）。
- 不做 Shell 扩展（COM）黑名单/删除管理。
- 不替换 explorer 自身（不做第三方 shell）。
- 不自动重启资源管理器（仅显式按钮触发，弹窗强提示）。
- 不实现 `IExplorerCommand` 的 C#/Python 版（官方不支持，二期走 Rust）。

## 2. 关键设计决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | **JSON 账本 + 注册表投影**：全部意图态存 `data/right_menu/state.json`，注册表是实现层 | 可导出/导入、可一键还原、重装可恢复；纯扫注册表无法区分「我禁用的」与「系统本来就没启用」 |
| D2 | **DLL ↔ Python 桥走 JSON 文件**（`win11.json`，mtime 缓存） | 命名管道/COM 查询复杂度高一个量级，且 DLL 运行在 explorer 代理进程（dllhost）内，稳定性优先 |
| D3 | **提权走独立作业进程** `YZplan.exe --elevated-job <job.json>` | 爆炸半径小：GUI 不提权；作业在 Qt 导入前执行、不进 GUI、不抢单实例锁；对 D 盘兜底 `ShellExecuteW("runas")` |
| D4 | **YZplan 系统右键子菜单一期走经典注册表动词**（`HKCU\...\shell\YZplan` 嵌套子键级联） | 零原生代码即可交付；Win11 新菜单注入属 M8，偏好项里提供切换 |
| D5 | **隐藏机制用官方 `LegacyDisable` + `ProgrammaticAccessOnly`** | MSDN 后向兼容标准做法，隐藏而不删除，可无备份恢复（写值前仍记录原值） |
| D6 | **类型过滤投影到 `SystemFileAssociations`** | 文档化位置，不碰文件关联，避免污染用户默认打开方式 |
| D7 | **操作层纯 Python，不 import PySide6** | 无 QApplication 可单测（沿 proxy_ctrl 分层先例） |
| D8 | **注册表后端 Protocol + Fake 注入** | 单测零真实注册表依赖（沿 envstore 先例） |

## 3. 架构

```
UI 层          widgets/home_widget.py  widgets/page.py  widgets/editor_dialog.py
               只做渲染与事件转发；阻塞操作经 QThread
    │
操作层         ops.py  scan.py  shellnew.py  classic.py  custom.py  yzmenu.py
（纯 Python）  registry_backend.py（winreg 惰性导入；Protocol + Fake）
    │
状态层         store.py  （data/right_menu/state.json + backups/）
    │
提权层         elevate.py  +  main.py 早退通道（--elevated-job）
    │
原生层（二期） native/win11_ctx/（Rust cdylib: IExplorerCommand + IClassFactory）
               独立 crate，不 import 任何 Python；渲染源 win11.json
```

依赖单向向下；操作层可直接单测，UI 层仅做组装。

## 4. 文件清单

### 一期（M1–M7）

```
modules/right_menu/
  __init__.py            导出 MODULE_INFO / Module（registry 自动发现契约）
  module.py              ModuleBase 子类；start/stop；菜单动作分发入口
  registry_backend.py    注册表读写抽象：Win32Backend / FakeRegistry（测试）
  store.py               state.json 账本：load/save/backup/一键还原快照
  scan.py                四大作用域右键项枚举与元数据解析（ShellNew 由 shellnew.py 负责）
  ops.py                 隐藏/恢复/删除统一操作（写 LegacyDisable 等）+ 还原账本
  shellnew.py            ShellNew 专项：枚举/隐藏/恢复/新增（NullFile、FileName 模板）
  classic.py             经典菜单总开关（CLSID 86ca1aa0…）+ 状态检测
  custom.py              自定义项 CRUD + 命令模板展开 + SystemFileAssociations 投影
  yzmenu.py              YZplan 系统右键菜单安装/卸载/动作清单
  elevate.py             提权作业：序列化、启动（runas）、结果读取
  widgets/
    __init__.py
    home_widget.py       首页小卡：经典菜单状态 + 隐藏项计数 + 快捷开关
    page.py              详情页（frameless + QTabWidget 五标签）
    editor_dialog.py     自定义项编辑器（含多级子菜单树）+ 类型过滤编辑
    restore_dialog.py    一键还原确认（列改动清单）
tests/
  test_right_menu_store.py
  test_right_menu_scan.py
  test_right_menu_ops.py
  test_right_menu_shellnew.py
  test_right_menu_classic.py
  test_right_menu_custom.py
  test_right_menu_yzmenu.py
  test_right_menu_elevate.py
  test_right_menu_ui.py
```

### 二期（M8）

```
native/win11_ctx/
  Cargo.toml
  build.rs               嵌入清单/资源
  src/lib.rs             COM 类工厂、DllGetClassObject/DllCanUnloadNow
  src/command.rs         IExplorerCommand（EnumSubCommands 递归子菜单）
  src/config.rs          win11.json 加载 + mtime 缓存 + 容错
  src/launch.rs          命令启动（%1/%* 展开、ShellExecuteW）
  manifest/AppxManifest.xml  稀疏包清单（desktop5:Verb × {*, Directory, Directory\Background}）
  scripts/build.ps1      构建 + 自签名 + 注册
docs/superpowers/specs/ 本文件（设计）；plans/ 实施计划
```

## 5. 组件契约

### 5.1 `registry_backend.RegistryBackend(Protocol)`

```python
class RegistryBackend(Protocol):
    def get(self, hive, path, name=None) -> str | None: ...
    def set(self, hive, path, name, value) -> None: ...
    def delete(self, hive, path, name=None) -> None: ...      # 不存在静默成功
    def delete_tree(self, hive, path) -> None: ...
    def list_keys(self, hive, path) -> list[str]: ...
    def list_values(self, hive, path) -> list[tuple[str, str]]: ...
```

- `Win32Backend` 惰性 `import winreg`；所有调用包装为永不抛异常（错误→None/空列表）
- `FakeRegistry`：内存树，测试注入；`Hive` 用字符串常量 `"HKCU"/"HKLM"`，backend 内部映射

### 5.2 `scan`

```python
SCOPES = ("file", "directory", "background", "drive")   # * / Directory / Directory\Background / Drive

def scan_scope(backend, scope, *, include_hklm=True) -> list[MenuItem]
```

ShellNew 的枚举在 `shellnew.scan_shellnew`（见 5.4），不在本模块。`scan.py` 只处理
四大作用域的右键项。

`MenuItem` 字段：`scope`、`key_path`、`hive`、`display_name`、`command`、`icon`、`extended`
（仅 Shift）、`disabled`（当前是否有 LegacyDisable/ProgrammaticAccessOnly）、`children`
（级联子项）、`source`（`hkcu/hklm`）。

元数据解析规则：

| 显示名来源（按优先级） | 命令来源 | 图标来源 |
|---|---|---|
| 子键 `MUIVerb`（含 `@dll,-id` 间接串则显示原始串+标注） | `command` 子键默认值 | `Icon` 值（原样展示，不解析间接资源） |
| 子键默认值 | `DelegateExecute`（Win11 内建项，标注） | `Icon` / `DefaultIcon` |
| 键名（兜底，如 `open`） | 无 command 且无子键 → 标注「无命令」 | — |

- 作用域路径：`file` = HKCU+HKLM `Software\Classes\*` 与 `AllFilesystemObjects`；
  `directory` = `\Directory`；`background` = `\Directory\Background`；`drive` = `\Drive`
- 过滤：跳过 `shellex`（COM 扩展）、`ShellEx`、纯 `\|` 分隔的内建伪项（如 Windows 自带的
  某些 CommandStore 项无 `command` 子键，标注「系统内建」）
- 排序：禁用项排后、按显示名 locale 排序

### 5.3 `ops`

```python
def apply_op(backend, op: dict, *, store=None) -> dict   # {"ok": bool, "detail": str}
```

- `op` 形态：`{"action": "disable"|"restore"|"delete"|"rename", "target": {...}, "hive": "hkcu"|"hklm"}`
- **disable**：写空值 `LegacyDisable`（唯一机制，M2 即此）。`ProgrammaticAccessOnly` 不在 M2
  引入；若实机验收发现某项在 Win11 新菜单中仍显示，记录到 M8 由 DLL 侧统一过滤（见风险 7）
- **restore**：按账本删除我们写过的值；无账本记录时仅删 `LegacyDisable`
- **delete**：仅允许删除 `source == hkcu` 且非系统内建的项；HKLM 一律走提权作业
- HKLM 操作：`ops` 检出 hive 后经 `elevate.run_job()` 提权，不在本进程直写
- 所有写操作前调用 `store.backup_snapshot()` 存一串最小还原信息

### 5.4 `shellnew`

```python
def scan_shellnew(backend) -> list[ShellNewItem]
def hide_shellnew(backend, item) -> dict      # 值名重命名加后缀
def restore_shellnew(backend, item) -> dict
def create_shellnew(backend, ext, *, name, kind, template_path=None) -> dict
```

- 扫描 `HKCU\Software\Classes\.<ext>\ShellNew` 与 HKLM 同名路径；`<ext>` 从 `Software\Classes` 一层子键中筛 `.` 开头者
- 值种类：`NullFile`（空文件）、`FileName`（模板文件路径）、`Data`（内联数据）、`Command`
- **隐藏**：值名 `NullFile` → `NullFile__yzhidden`（前缀保留原值名+固定后缀，shell 不识别非规范值名）；恢复=改回。
  HKLM 来源的 ShellNew 隐藏经 `elevate.run_job` 提权执行，HKCU 直写
- **新增**：扩展名必须 `^\.[A-Za-z0-9_.-]{1,30}$`；`kind=="null"` 写 `NullFile=""`；
  `kind=="template"` 把源文件拷入 `data/right_menu/templates/<uuid>_<原名>` 再写 `FileName=<绝对路径>`；
  HKCU 级，无需提权；已存在同名项时拒绝并提示
- 系统项（HKLM 来源）**只允许隐藏，不允许删除**；HKCU 用户项允许删除

### 5.5 `classic`

```python
def get_classic_state(backend) -> str      # "enabled" | "disabled" | "unknown"
def enable_classic(backend) -> dict        # 写空字符串 InprocServer32 默认值
def disable_classic(backend) -> dict       # 删除 CLSID 键
def restart_explorer() -> dict             # taskkill /f /im explorer.exe + start explorer.exe
```

- 经典开关 = `HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32`
  默认值 `""`；状态检测：该键存在且默认值为 `""` → enabled
- 需重启 explorer 生效；`restart_explorer` 明确弹窗提示后由用户确认调用
- **Win11 24H2+ / Insider 26220 上此机制可能已被移除**：M3 实机验收必须含「开关往返 +
  菜单实际样式观察」，失败则记录并降级为「不提供」；不阻塞其他里程碑

### 5.6 `custom`（自定义项）

DOM 形态（存 store，投影到注册表）：

```jsonc
{
  "id": "uuid",
  "title": "用 VSCode 打开",
  "icon": "C:\\...\\Code.exe,0",        // 可空
  "scope": "file",                       // file/directory/background/drive
  "ext_filter": [".py", ".txt"],         // 仅 scope=file 有效；空=全部
  "hive": "hkcu",                        // hkcu 默认；hklm 需提权
  "extended": false,                     // true=仅 Shift 右键显示
  "position": "bottom",                  // top/bottom（默认值排序）
  "action": {
    "kind": "command",                   // command/program/url/open
    "target": "code",                    // 程序/PowerShell 片段/URL/路径
    "args": "\"%1\"",                    // 支持 %1 %* %V 占位
    "workdir": ""
  },
  "children": []                         // 递归子菜单，同构节点
}
```

- 展开规则：`%1` = 选中单个路径（多选时取第一个）；`%*` = 全部选中路径；`%V` = 当前目录；
  未加引号路径自动加引号；写注册表时 `command` 默认值 = `target + " " + args`
- 投影：
  - `scope=file` 无扩展名过滤 → `HKCU\Software\Classes\*\shell\<slug>`
  - `scope=file` 带过滤 → 每扩展名一条 `HKCU\Software\Classes\SystemFileAssociations\<ext>\shell\<slug>`
  - 其余作用域 → 对应 `Directory` / `Directory\Background` / `Drive` 的 `shell\<slug>`
  - 子菜单：父键建 `SubCommands` 空值 + `shell` 子键（命令项挂子键下）；`MUIVerb`=标题、
    `Icon`=图标、`Extended` 空值=仅 Shift、`Position`=`Top`/`Bottom`
- 危险校验：`target`/`args` 中出现 `%` 后跟非法字符、未加引号含空格路径（提示）、
  `cmd /c` 系列模板给出示例确认；拒绝空 target

### 5.7 `yzmenu`（YZplan 系统右键子菜单）

```python
ACTIONS = ["open_manager", "toggle_classic", "show_window", "restore_all"]
def install_yzmenu(backend, actions: list[str]) -> dict
def uninstall_yzmenu(backend) -> dict
def get_yzmenu_state(backend) -> dict     # {"installed": bool, "actions": [...]}
```

- 位置：`HKCU\Software\Classes\{*|Directory|Directory\Background}\shell\YZplan`
  （`MUIVerb="YZplan"`、`Icon=YZplan.exe`、`SubCommands=""`、`Position="Top"`）
- 子动作 = `shell\YZplan\shell\<action>`，命令 = `<YZplan.exe> --menu-action <action>`
- `open_manager` → `--menu-action open_manager`；已运行实例经 mcp_inbox 收到命令后
  `open_module_page("right_menu")`；未运行则正常启动后执行动作（见 5.9）
- 卸载 = `delete_tree` YZplan 键；不影响其他项

### 5.8 `store`

- 路径：`<DATA_DIR>/right_menu/state.json`；备份目录 `<DATA_DIR>/right_menu/backups/`
- 结构：

```jsonc
{
  "schema": 1,
  "disabled": [ {"hive":"hkcu","key_path":"...","name":"LegacyDisable","original":null,"ts":"..."} ],
  "shellnew_hidden": [ {"hive":"hkcu","path":"...","orig_name":"NullFile","ts":"..."} ],
  "custom_items": [ {...5.6 DOM...} ],
  "yzmenu": {"installed": true, "actions": ["open_manager"]},
  "restore_points": [ {"id":"...","reason":"...","changes":[...],"ts":"..."} ]
}
```

- `load()` 损坏返回空账本；`save()` 返回 bool；`backup_snapshot(reason)` 写 `backups/<ts>.json`
- **一键还原** `restore_all(backend)`：逐条撤销账本（LegacyDisable 恢复原值/删除、
  ShellNew 改名恢复、删自定义投影、卸 YZmenu、关经典菜单），产出操作报告

### 5.9 `elevate` 与 `--elevated-job`

```python
def run_job(job: dict, *, timeout: float = 60) -> dict   # 序列化→启动→等结果
```

- 作业文件：`data/right_menu/elevated/job_<id>.json`；结果 `job_<id>.result.json`
- `launch`：优先 `ShellExecuteW(None, "runas", sys.executable, "--elevated-job <path>", ...)`；
  frozen 时 `sys.executable` 即 `YZplan.exe`；dev 时用 `pythonw.exe` + `main.py`
- **main.py 早退通道**（任何 Qt import 之前）：

```python
if "--elevated-job" in sys.argv:
    from modules.right_menu.elevate import run_elevated_job
    sys.exit(run_elevated_job(sys.argv[...]))   # 不创建 QApplication、不碰互斥量
```

- `--menu-action` 通道：无运行实例时作为首次启动参数暂存（`context` 传递到模块 start()），
  有运行实例时写 mcp_inbox `{"command": "menu_action", "action": ...}` 后退出
- 单实例互斥量分支（main.py 顶部）目前是硬退出：**修改为**先尝试写 mcp_inbox
  `menu_action`（仅当 argv 含 `--menu-action`），再 `os._exit(0)`

### 5.10 `module.py` 菜单动作分发

`Module.start()` 读取 `context.pending_menu_action`（若存在）→ 经
`QTimer.singleShot(0, dispatch)` 在主循环开始后打开页面/执行动作。

## 6. 数据流

### 扫描（M1）

```
用户切标签/点刷新
  → page 组装 scope 列表
  → QThread: scan.scan_scope(backend, scope) + scan.scan_shellnew(backend)
  → signal 回 UI，填表（名称/命令预览/来源徽章/状态 chip）
```

### 隐藏项（M2）

```
用户点「隐藏」
  → store.backup_snapshot("disable ...")
  → HKCU: ops.apply_op 直写；HKLM: elevate.run_job（UAC 弹窗）
  → 结果更新表格行状态 + InfoBar
  → （可选提示）重启 explorer 生效
```

### 经典开关（M3）

```
用户点「切换到经典菜单」
  → 强提示弹窗（需重启 explorer）
  → classic.enable_classic 直写 HKCU
  → 用户点「重启资源管理器」→ 确认 → restart_explorer
```

### 自定义项（M5）

```
编辑器对话框收集 DOM → custom.validate → store.save（账本）
  → custom.sync(backend) 重建该 item 在注册表中的投影（先删后建，幂等）
  → HKLM 时改走 elevate
```

### YZplan 右键（M6）

```
安装：yzmenu.install_yzmenu(backend, actions)
点击菜单：YZplan.exe --menu-action open_manager
  已运行 → 写 mcp_inbox → 现有实例 open_module_page
  未运行 → 启动，Module.start() 消费 pending_menu_action
```

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| 账本损坏/缺失 | 返回空账本，界面提示「无历史记录」；不阻塞扫描 |
| 注册表读取失败（权限/项缺失） | 该项标注「不可读」，其余继续 |
| HKLM 写被拒（用户点否 UAC） | 作业返回 `{"ok": false, "error": "cancelled"}`；提示「已取消，未做任何修改」 |
| 提权作业超时 | 60s 超时；提示「未收到结果，请检查」；作业文件保留供排查 |
| ShellNew 新增冲突 | 拒绝并提示已存在的项名 |
| 扩展名非法 | 拒绝并列合法格式 |
| 自定义项 target 为空 | 表单校验拒绝 |
| 命令展开含未引用空格路径 | 警告（可继续） |
| explorer 重启失败 | 提示手动重启（任务管理器） |
| 经典机制在新系统无效 | M3 验收记录，UI 标注「当前系统不支持」 |
| Win11 新菜单 DLL 崩溃 | DLL 内全兜底：配置解析失败→空菜单；不 panic 到 COM 边界（M8） |
| 禁用项的 command 为空 | 扫描时标注「系统内建/无命令」，仍允许隐藏 |

## 8. UI

### 首页小卡（`create_home_widget`）

- 经典菜单状态 chip（经典/新版/未知）
- 「已隐藏右键项」计数、自定义项计数
- 两个按钮：「打开管理器」「切换经典菜单」
- 30s QTimer 刷新，`destroyed` 时停表（沿 proxy_ctrl 先例）

### 详情页（`create_page`，frameless + QTabWidget 五标签）

1. **右键项**：作用域分段控件（文件/文件夹/背景/驱动器）+ 搜索框 + 刷新；表格列 =
   名称 / 作用域 / 命令预览（截断+悬浮全文）/ 来源徽章 / 状态 chip / 操作（隐藏·恢复）
2. **新建菜单**：ShellNew 表（扩展名 / 类型 chip / 模板路径 / 状态 / 隐藏·恢复·删除）+
   「新增模板」按钮（对话框：扩展名+空文件/模板文件选择）
3. **经典菜单**：状态卡片 + 「切换」按钮 + 「重启资源管理器」按钮（红色危险样式 + 确认）
4. **自定义项**：列表 + 新建/编辑/删除 + 上移/下移 + 导出/导入 JSON；编辑器对话框含
   标题/图标/作用域/扩展名过滤（可多个）/命令类型/参数/工作目录/仅 Shift/位置/子菜单树
5. **设置**：YZplan 右键子菜单（安装开关 + 动作多选）、一键还原、备份列表、数据目录按钮

标题栏：`title_bar_spec` 放「刷新」「打开数据目录」两个文字按钮（`frameless=True`）。

## 9. 与主程序/基础设施的改动清单

1. `main.py`：新增 `--elevated-job` 早退通道（必须在任何 Qt import 之前）；单实例分支支持
   `--menu-action` 写 mcp_inbox 后退出；`--menu-action` 作为首次启动时存入 `context.pending_menu_action`
2. `core/tray/mcp.py`：dispatch 增加 `"menu_action"` → `_mcp_menu_action(action)`
   （内部调 `registry.get("right_menu")` 分发；不要求模块已启用时静默跳过）
3. `mcp_server/tools_right_menu.py` + `mcp_server/__init__.py`：新切片注册
4. `tests/conftest.py`：`_isolate_db` 增加 right_menu 的 `state.json` 与 `backups/` 路径 monkeypatch
5. `.gitignore`：追加 `data/right_menu/`（含用户自定义项与备份，属机器本地数据）
6. `.github/workflows/python-app.yml`：新测试文件登记进 4 个 chunk
7. `yzplan.spec`（M8 时）：打包 `native/win11_ctx/` 产出的 DLL 与 MSIX 资源

## 10. MCP 工具设计（M7）

| 工具名 | 说明 | 写方式 |
|---|---|---|
| `right_menu_scan` | 扫描指定作用域（file/directory/background/drive/all）+ ShellNew | 只读直连 |
| `right_menu_set_disabled` | 隐藏/恢复某项（hive+key_path） | HKCU 直写；HKLM 提示需 GUI/返回错误码 |
| `right_menu_classic_state` | 查询经典菜单状态 | 只读直连 |
| `right_menu_classic_set` | 开关经典菜单 | HKCU 直写 |
| `right_menu_custom_list` / `_save` / `_delete` | 自定义项 CRUD | 写 store 直连 + sync 注册表 |
| `right_menu_shellnew_scan` / `_hide` / `_restore` | ShellNew 管理 | HKCU 直写 |
| `right_menu_restore_all` | 一键还原 | 直连 + 报告 |
| `right_menu_open_manager` | 打开模块页面（GUI IPC） | mcp_inbox |

MCP 进程与 GUI 并行的注意事项：MCP 写 store 后 GUI 侧读 mtime 或每次刷新重读，
避免双写内存态冲突；写注册表与 GUI 相同路径时同样先备份。

## 11. 样式与令牌合规

- 控件全部经 `ui/widgets.py` 工厂；颜色取 `theme_palette()`、尺寸取 `sizing()`
- 无私有调色板函数；表格样式函数接收 palette dict 参数
- 需新增令牌时先改 `core/theme/tokens.py`（预期零新增）
- 单文件 ≤ 250 行；`page.py` 超限时拆 `widgets/page_tabs/*.py`

## 12. 测试策略（TDD）

| 文件 | 覆盖 |
|---|---|
| `test_right_menu_store.py` | 空/损坏账本；备份快照；restore_all 逐类撤销；隔离 monkeypatch |
| `test_right_menu_scan.py` | FakeRegistry 注入：四作用域枚举、显示名/命令/图标解析、扩展名过滤、禁用标记、排序 |
| `test_right_menu_ops.py` | 隐藏写 LegacyDisable、原值账本；恢复删除；HKLM 走 elevate（假 elevate）；delete 保护规则 |
| `test_right_menu_shellnew.py` | 枚举；隐藏改名往返；新增 null/template；非法扩展名拒绝；系统项保护；路径遍历防护 |
| `test_right_menu_classic.py` | 状态三态；开关往返；restart_explorer 命令构造（假 subprocess） |
| `test_right_menu_custom.py` | DOM 校验；%1/%*/%V 展开（含引号）；SystemFileAssociations 投影路径；子菜单 SubCommands 结构；sync 幂等 |
| `test_right_menu_yzmenu.py` | 安装/卸载键结构；动作子键；状态读取 |
| `test_right_menu_elevate.py` | 作业序列化/结果读取（假 Popen）；超时；main.py 通道参数解析 |
| `test_right_menu_ui.py` | offscreen：首页卡、详情页五标签、编辑器对话框、还原确认框构建 |

规则：无真实注册表写入（FakeRegistry）；`store` 路径 monkeypatch 到 tmp_path；
`QT_QPA_PLATFORM` 仅 setdefault；QApplication 只经 `qapp` fixture；新文件登记 CI chunk。

**实机手动验收清单（每里程碑）**：M2 隐藏一个 HKCU 项→重启 explorer→肉眼确认消失→恢复；
M3 经典切换→确认样式变化；M4 新增空文件模板→桌面新建菜单出现；M5 自定义项全类型各建一条；
M6 右键 YZplan 子菜单各动作；M8 新菜单注入 + 卸载残留检查。

## 13. 验收标准

### 一期（M1–M7）

1. `python -m pytest tests/test_right_menu_*.py -v` 全绿。
2. `python scripts/audit_styles.py --check` 无新增违规；`pytest tests/test_style_guardrails.py -v` 通过。
3. FakeRegistry 单测零真实注册表依赖（测试运行前后 `HKCU\Software\Classes\*` 无变化）。
4. 实机：隐藏/恢复往返正确（含 explorer 重启后肉眼确认）。
5. 实机：自定义项四作用域各一条可用；多级子菜单展开；`%1` 在真实多选文件下行为符合文档。
6. 实机：YZplan 子菜单在文件/文件夹/桌面背景三处出现；点击后已运行实例跳到模块页。
7. 一键还原后本模块在 `HKCU\Software\Classes` 与 `HKCU\Software\Classes\CLSID` 的残留为零：
   导出还原前后两份注册表快照（`reg export` 输出）人工比对，仅允许出现无关系统差异。
8. 新文件全部登记进 CI 4 chunk；`data/right_menu/` 已加入 .gitignore。

### 二期（M8）

9. Rust 单测（JSON 解析/命令展开/容错）通过；`cargo build --release` 产出 DLL。
10. 稀疏包注册成功（开发者模式），Win11 新版右键出现注入项；卸载后无残留项。
11. `GetTitle/GetState` 在 explorer 中无肉眼可见卡顿（快速右键多次）。
12. 配置损坏注入（手工改坏 win11.json）→ 菜单显示为空、explorer 不崩。

## 14. 里程碑与依赖

| 里程碑 | 内容 | 依赖 |
|---|---|---|
| M1 | 骨架 + store + scan + 只读页（右键项/新建菜单两标签） | 无 |
| M2 | ops + 提权通道 + 隐藏/恢复 | M1 |
| M3 | classic 开关 + explorer 重启 | M1 |
| M4 | shellnew 管理（隐藏/恢复/新增） | M1、M2（提权复用可选） |
| M5 | custom 全套 + 编辑器对话框 | M2（HKLM 路径） |
| M6 | yzmenu + `--menu-action` IPC + 单实例分支改造 | M2 |
| M7 | MCP 切片 | M1–M6 |
| M8 | Rust DLL + 稀疏包 + Win11 注入 | 全部；先装 VS Build Tools + rustup（用户确认后） |

## 15. 风险与开放项

1. **Win11 Insider 26220 行为漂移**：经典 CLSID 开关、稀疏包注册都可能与文档不同；M3/M8
   实机验证优先，失败降级不阻塞。
2. **HKLM 全用户级变更**：UI 强警告 + 备份 + 一键还原；测试绝不打真实 HKLM。
3. **稀疏包签名**：开发者模式注册优先；失败走自签名流程（预留脚本位）；仍失败则 M8 降级搁置。
4. **全量扫描性能**：`Software\Classes` 子键极多，扫描限定四作用域 + ShellNew 专项；
   扩展名类扫描（SystemFileAssociations）只按需查询，不做全量遍历。
5. **DLL 稳定性**：dllhost 代理进程内兜底不 panic；M8 专项崩溃竞测。
6. **MCP 与 GUI 双写**：以 mtime 检测 + 操作前重读为准；文档化「GUI 打开时优先用 GUI」。
7. **`LegacyDisable` 对 Win11 新菜单项无效**：部分项在新菜单中由别机制渲染，M2 验收含
   「隐藏后新菜单也消失」检查；不消失的记录并在 M8 由 DLL 侧统一过滤。

## 16. 不做的事（明确排除）

- 不修改文件关联、不动 `HKCR` 合并视图的 ProgID 默认值
- 不删系统项（HKLM 仅隐藏）
- 不自动重启 explorer、不静默提权
- 不引入第三方 shell 方案（Nilesoft 等）
- 不做右键项「重命名显示名」的通用改写（超出必要；自定义项标题除外）
- 不为 Win10 做特殊适配路径（以 Win11 为主，机制本身兼容 Win10）
