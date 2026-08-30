# YZplan

一个基于 PySide6 / PyQt-Fluent-Widgets 的 Windows 桌面应用。首页采用「纵向卡片列表」组件面板：卡片永不重叠、可上下移动排序、自由调整大小，并自动保存布局；配合模块页、设置页、关于页与全局托盘的 Fluent 风格界面。

> English: [README.en.md](README.en.md)

## 功能特性

- **主页组件面板**：纵向卡片列表
  - 卡片**永不重叠**，标题栏提供 `上移` / `下移` / `移除`
  - 组件宽高无级拖拽调整，顺序与尺寸自动保存，重启后保持
  - 添加组件、恢复默认顺序、清空布局
  - 手动调整大小与自动布局，重启后保持
- **系统信息模块**：CPU / 内存 / 磁盘等
- **路径直达模块**：快速打开常用路径
- **RSS 聚合模块**
  - 订阅源抓取、阅读、**通知**与自动刷新
  - **多标签**分类，标签筛选下拉
  - **聚合（分组）**：分组头来源徽标展开/折叠、一键勾选全选、批量操作（已读/未读/删除）
  - 条目列表轻量化（不展示图片），预览区顶部显示**摘要**（标题/标签/更新时间/描述）
- **Fluent 风格界面**：浅色 / 深色 / 跟随系统主题切换、壁纸背景与毛玻璃效果
- 主窗口**首启按屏幕自适应**尺寸与位置，关闭时最小化到托盘、开机自启、全局快捷键

## 环境要求

- Windows
- Python 3.11+（64 位）

## 环境搭建

```bat
:: 在项目根目录创建虚拟环境
python -m venv .venv

:: 激活虚拟环境
.venv\Scripts\activate

:: 安装依赖
pip install -r requirements.txt
```

## 运行

```bat
run.bat
```

或：

```bat
.venv\Scripts\python main.py
```

首次运行会自动创建 `data/` 目录（含 `settings.json`、`app.db`、`logs/` 等运行时数据）。

## 测试

```bat
.venv\Scripts\python -m pytest
```

也可运行冒烟测试：

```bat
.venv\Scripts\python smoke_test.py
```

## 打包为可执行文件

使用 PyInstaller（onedir 模式）：

```bat
build.bat
```

> **推荐使用标准 python.org 的 CPython（64 位）创建虚拟环境**，即 `python -m venv .venv` 后执行
> `pip install -r requirements.txt`。`requirements.txt` 中全部是标准 pip 包，不依赖 anaconda，
> 在任何干净的标准 CPython 环境都能正常安装与构建。

`yzplan.spec` 会自动适配两种环境，无需手动设置任何环境变量：

- **标准 CPython venv**：PyInstaller 自动收集所有编译扩展模块与原生 DLL，直接构建即可。
- **conda / anaconda venv**：spec 会自动探测 conda base，把标准库扩展模块（`_ctypes.pyd` 等）
  和 `Library\bin` 下的 `sqlite3.dll`、`libssl`/`libcrypto` 等 DLL 一并打包，避免冻结后的
  程序报 `DLL load failed while importing _ctypes`。

如自动探测偶有误判，可用 `YZPLAN_CONDA_ROOT` 环境变量手动指定 conda 根目录：

```bat
set YZPLAN_CONDA_ROOT=C:\path\to\your\anaconda3
build.bat
```

## 目录结构

```
.
├─ main.py            # 程序入口
├─ core/              # 核心：配置、主题、托盘、单实例、日志等
├─ ui/                # 界面：主窗口、各选项卡
├─ modules/           # 功能模块
├─ tests/             # 单元测试
├─ data/              # 运行时数据（不入库）
├─ requirements.txt   # 依赖清单
├─ yzplan.spec        # PyInstaller 打包配置
└─ build.bat / run.bat
```

## 说明

- `data/`、`.venv/`、`build/`、`dist/` 等均为本地生成内容，已通过 `.gitignore` 排除，不会提交到仓库。
- 个人配置（如壁纸路径）、RSS 数据均位于 `data/` 中，不随仓库同步。

## 许可证

GPL-3.0，详见 [LICENSE](LICENSE)。
