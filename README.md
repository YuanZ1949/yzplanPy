# YZplan

一个基于 PySide6 / PyQt-Fluent-Widgets 的 Windows 桌面应用。首页采用「画布式」组件面板：组件可自由拖拽移动、无级拖拽调整大小、拖动重新排序，瀑布流布局会自动按窗口宽度自适应并且填充度较高的行自动拉伸填满整行，无右侧空白。

> English: [README.en.md](README.en.md)

## 功能特性

- **主页组件面板**：瀑布流自适应布局
  - 组件可拖拽移动、拖动交换顺序（**仅拖动时**，点击按钮不会触发换序）
  - 组件宽高**无级拖拽调整**，尺寸自动保存，重启后保持
  - 窗口拉大时，填充度较高的行自动拉伸铺满，不留右侧空白
  - 添加/移除组件、重置/清空布局
- **系统信息模块**：CPU / 内存 / 磁盘等
- **路径直达模块**：快速打开常用路径
- **RSS 聚合模块**：订阅源抓取、阅读、通知
- Fluent 风格界面主题（浅色 / 深色 / 跟随系统）、壁纸背景与毛玻璃效果
- 关闭时最小化到托盘、开机自启、全局快捷键

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

> **注意**：`yzplan.spec` 需要从你的 conda/anaconda 环境复制 `sqlite3.dll`、`libcrypto` 等 DLL。
> 请在打包前设置环境变量指向你的 conda `Library\bin` 目录：

```bat
set YZPLAN_CONDA_BIN=C:\path\to\your\anaconda3\Library\bin
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
