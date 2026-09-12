# GUI 样式系统性统一设计

日期：2026-09-12
状态：设计稿（待用户审查）

## 1. 背景与问题

用户长期反馈三个反复出现、多次修改仍无法根治的 GUI 问题：

| 症状 | 代码根因 |
|---|---|
| **1. 按钮/控件高度风格不一致** | 17 个文件共 30 处手写 `setFixedHeight`/`setMinimumHeight`；26 个文件共 83 处手写 `font-size`/`padding` QSS。每个模块自行定义按钮样式（RSS 有独立 `_btn_style()`、`_migrated_btn_qss()`，主窗口有 `_TextTitleBarButton`），无任何共享控件规格 |
| **2. 文字截断、图标与文字混叠** | 控件高度为写死的像素值，而程序支持 0.7~1.6 倍字体缩放；字号放大后固定高度装不下文字即截断。图标+文字按钮按图标宽度布局，追加文字后溢出 |
| **3. 主题更换后角落不统一** | 存在三套并行调色板：全局 QSS（`qss_dark.py`/`qss_light.py`）、RSS 模块私有 `_rss_colors()`、perf_monitor 私有 `_theme_colors()`，外加各处硬编码 hex。改全局主题时模块内联样式不刷新，永远有漏网 |

**根本原因**：样式定义散落于 26+ 文件、无单一事实来源（single source of truth），无开发期护栏防止新的散落产生。

## 2. 目标与原则

- **目标**：建立全局唯一的设计令牌与共享控件工厂，所有颜色/尺寸/字体从单一来源取值，禁止硬编码。
- **配色基准**：以 perf_monitor 模块 `_theme_colors()` 为基准（用户指定），提升为全局唯一调色板。
- **护栏**：全部支持四道护栏（控件工厂 API、静态扫描、运行时测试、开发规范）。
- 迁移过程不破坏现有功能，逐模块替换并截图对比验证。

## 3. 架构设计

### 3.1 设计令牌 `core/theme/tokens.py`

全局唯一的视觉属性来源。要点：

- `theme_palette()`：函数（非常量），每次调用按当前 `resolve_dark("auto")` 实时返回明/暗调色板，支持运行时主题热切换。色值以 perf_monitor `_theme_colors()` 为基准；perf_monitor 缺失但全局 QSS 已使用的语义色（accent_hover/pressed、success/warning/danger/info、text_disabled、border_focus 等）从 `qss_dark.py`/`qss_light.py` 现有值中提取合并，保证视觉跳变最小。
- `Sizing` 类：尺寸令牌。所有像素值经 `_s(px)` 按 `current_font_scale()`（0.7~1.6）缩放，保证字号放大时高度/间距/圆角同步增长——根治截断问题。`_s()` 在属性访问时计算（类属性），支持运行时字体缩放切换。
- 令牌分类：
  - 颜色：accent 系列、语义色、面板背景、边框、文字、特殊胶囊色（chip_torrent/chip_article，供 RSS 使用）
  - 尺寸：BTN_HEIGHT_SM/MD/LG、BTN_PADDING_*、INPUT_HEIGHT、COMBO_HEIGHT、RADIUS_SM/MD/LG
  - 字号：FONT_SIZE_XS/SM/MD/LG/XL

### 3.2 控件工厂 `ui/widgets.py`

覆盖全部高频控件，调用方只能传语义参数（kind/size/role），内部读取令牌。

| 工厂函数 | 覆盖控件 | 语义参数 |
|---|---|---|
| `make_button` | 普通/主色/危险/幽灵/平铺按钮 | `kind`（default/primary/danger/ghost/flat）、`size`（sm/md/lg）、`icon` |
| `make_line_edit` | 输入框 | `placeholder` |
| `make_combo` | 下拉框 | `items` |
| `make_card` | 卡片容器 QFrame | 无 |
| `make_status_chip` | 状态胶囊 | `kind`（torrent/article/success/info） |
| `make_label` | 标题/副标题/正文/说明/弱化文字 | `role`（title/subtitle/body/caption/muted） |

约束：
- 工厂内部必须使用 `theme_palette()` 与 `Sizing`，禁止在工厂内硬编码颜色/尺寸。
- 图标+文字按钮由工厂统一设置图标并保证文字完整（大小尺寸令牌已含缩放）。
- 复杂自定义控件（如 RSS 侧边栏、列表行、图表）不进工厂，但**必须从 `theme_palette()` 取色**，禁止私有调色板与内联 hex。

### 3.3 全局 QSS 与令牌的关系

- `qss_dark.py`/`qss_light.py` 的全局基础样式保持不变（兜底），但其内分散的颜色值后续（阶段 3 尾声）替换为 `theme_palette()` 引用，消除"第三套调色板"。
- 模块级 setStyleSheet 一律参数化：`setStyleSheet(样式函数(p))`，样式函数接收调色板，不内嵌颜色字面量。

## 4. 迁移路径（三个阶段）

### 阶段 1：建设（零破坏，纯增量）
1. 新增 `core/theme/tokens.py`（theme_palette + Sizing + _s 缩放）
2. 新增 `ui/widgets.py` 控件工厂
3. 编写静态扫描脚本 `scripts/audit_styles.py`（护栏 B 骨架，先宽松阈值）
4. 编写运行时测试框架 `tests/test_style_guardrails.py`（护栏 C 骨架：主题切换一致性、字体缩放无截断）
5. 开发规范文档（护栏 D）落地

### 阶段 2：新代码强制
- 本次涉及修改的代码与新写的模块强制走工厂 + 色板。
- 规范文档生效：禁止裸 `setFixedHeight` + hex 内联样式。

### 阶段 3：存量迁移
- 用扫描脚本产出硬编码清单（30 处尺寸 + 83 处内联样式 + 各模块私有调色板），逐模块替换。
- **替换顺序**（复杂度低→高）：
  1. `ui/` 层：title_bar_kit、settings_tab、home_tab、log_viewer
  2. `modules/perf_monitor`：`_theme_colors()` 切换为全局 `theme_palette()` 引用
  3. `modules/todo_notes`、`modules/sys_info`、`modules/screenshot`、`modules/webview_control`、`modules/translator`
  4. `modules/rss_aggregator`：最复杂（sidebar/styles/page_theme/page_layout 等，约 20 处内联样式 + 私有 `_rss_colors()`）
- **每个模块替换后必须截图对比（明/暗主题）确认无视觉退化**。

## 5. 四道护栏

### A. 控件工厂 API（设计层面强制）
新增控件一律走 `ui/widgets.py`。工厂是唯一允许触碰尺寸/颜色令牌的代码区。

### B. 静态扫描 `scripts/audit_styles.py`
违规即报错，接入 pre-commit/CI：
- `setFixedHeight`/`setMinimumHeight` 魔法数字（工厂内部豁免）
- QSS 字符串中的 `#[0-9a-fA-F]{6}` 硬编码颜色（工厂与 tokens 内部豁免）
- 模块内私有调色板 `def _xxx_colors()` / `_theme_colors()`（仅 `core/theme/` 允许）
- `setStyleSheet` 中字符串拼接的 rgb/hex 字面量

### C. 运行时测试 `tests/test_style_guardrails.py`
- **主题切换一致性**：切换明暗后遍历 `QApplication.allWidgets()` 可见控件，断言其 QSS 中出现的颜色值均存在于新调色板（无旧主题残留）。
- **字体缩放无截断**：`set_scale(1.6)` 后遍历所有按钮/输入框，用 `QFontMetrics` 断言文字+图标+内边距不超出控件宽高。
- RSS 等复杂控件单独冒烟：主题切换后 `_rss_colors()` 相关颜色全部来自 `theme_palette()`。

### D. 开发规范（AGENTS.md / 开发手册新增一节）
1. 新控件必须从 `ui/widgets.py` 工厂创建，禁止手动 `setFixedHeight` + `setStyleSheet`
2. 颜色必须从 `theme_palette()` 获取，禁止写 hex 字面量
3. 字号必须从 `Sizing.FONT_SIZE_*` 获取，禁止 `font-size: 13px`
4. 模块禁止拥有私有调色板
5. 修改控件样式前先确认/新增令牌，再引用

## 6. 验证方式

- 每个阶段结束：`pytest` 全绿（含新增护栏测试）。
- 阶段 3 每个模块替换后：明/暗主题截图对比，人工确认无视觉退化。
- 最终验收：`scripts/audit_styles.py` 零违规；主题切换测试、缩放测试通过。

## 7. 范围与边界

**范围内**：tokens/工厂/护栏/六个模块组的存量迁移。
**范围外**：不改变整体 UI 布局结构与交互；不引入第三方样式框架；不动 qfluentwidgets 内建导航/标题栏渲染机制。