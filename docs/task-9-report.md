# Task 9 报告：全局收尾——qss 兜底收敛 + 豁免收窄 + 最终验收

## 目标

- 迁移 7 个非白名单文件中的 **19 处 `size_literal` 遗留**到 `sizing()` 令牌。
- 将 `core/theme/qss_dark.py` / `qss_light.py` 内分散色值与尺寸收敛为
  `theme_palette()` / `sizing()` 引用（视觉零变化，值不变仅改来源）。
- 审计白名单收窄至最小集 `{core/theme/tokens.py, ui/widgets.py, scripts/audit_styles.py, tests/}`。
- 解决 7 个零引用 `rss_*` 孤儿键（T8 报告"偏差记录"遗留决策）。
- 重建基线：**20 → 0**，`audit --check` 零新增，全量 pytest 通过。

## 方案

### 1. 19 处 size_literal 迁移（7 文件）

| 文件 | 行 | 原值 | 令牌 |
|---|---|---|---|
| `core/tray/dialogs.py` | 72, 73, 75 | `width/height: 16px`、`border-radius: 3px` | `tray_indicator_size`、`tray_indicator_radius` |
| `core/tray/tray_base.py` | 125, 126 | `min-height: 20px`、`padding: 3px 24px 3px 12px` | `tray_item_min_height`、`tray_item_padding` |
| `modules/screenshot/screenshot_ui.py` | 113, 142 | `font-size: 18px`、`margin-bottom: 10px`、`font-size: 12px` | `shot_title_font_size`、`shot_title_margin_bottom`、`shot_status_font_size` |
| `modules/todo_notes/home.py` | 110-112, 120-124 | `border-radius: 9px`、`padding: 2px 10px`、`font-size: 12px`、`padding: 8px 10px`、`margin: 2px 0`、`border-radius: 8px`×4 | `todo_badge_radius`、`todo_badge_padding`、`todo_badge_font_size`、`todo_item_padding`、`todo_item_margin`、`todo_item_radius` |
| `ui/home_tab/picker.py` | 17, 22 | `border-radius: 12px` | `picker_radius` |
| `ui/settings_tab/mcp.py` | 42 | `border-radius: 6px`、`padding: 5px 10px` | `radius_md`、`mcp_cmd_padding` |
| `ui/settings_tab/rows.py` | 14, 46 | `font-size: 13px`、`margin-bottom: 2px`、`max-width: 200px` | `font_size_md`、`row_title_margin_bottom`、`wp_path_max_width` |

未触碰未违规色值（`#666`/`#888`/`#999`/rgba）——不在审计规则范围，P-9 保原值。

### 2. qss_dark/qss_light 收敛

- 函数签名 `_apply_dark_sheet(acrylic)` / `_apply_light_sheet(acrylic)` 不变
  （`styles.py` / `__init__.py` / `test_theme_borders.py` 依赖）。
- 函数内 `p = theme_palette(); sz = sizing()`，QSS 字符串 f-string 插值。
- 新增 **30 个 `qss_*` 调色板键**（明暗两套，值与原 qss 文件逐字节一致）：
  `qss_bg_acrylic`、`qss_list_sel_bg`、`qss_list_item_hover`、`qss_menu_sel_bg`、
  `qss_scrollbar_bg`、`qss_scrollbar_hover`、`qss_btn_bg`、`qss_btn_border`、
  `qss_btn_text`、`qss_btn_bg_hover`、`qss_btn_border_hover`、`qss_btn_bg_pressed`、
  `qss_input_bg`、`qss_input_border`、`qss_input_text`、`qss_selection_bg`、
  `qss_focus_border`、`qss_combo_bg`、`qss_indicator_border`、
  `qss_indicator_hover_border`、`qss_indicator_hover_bg`、`qss_indicator_checked_bg`、
  `qss_indicator_checked_border`、`qss_indicator_checked_hover_bg`、
  `qss_indicator_checked_hover_border`、`qss_indicator_disabled_border`、
  `qss_checkbox_disabled`、`qss_menu_bg`、`qss_menu_border`、`qss_dialog_bg`。
- 复用既有键（字节相同）：暗 `bg_app`/`rss_border`/`bg_hover`/`border`/`text_disabled`；
  亮 `bg_app`/`border`/`text_disabled`。
- 新增 **33 个 `sizing()` 令牌**（`tray_*`×4、`shot_*`×3、`todo_*`×7、`picker_radius`、
  `mcp_cmd_padding`、`row_title_margin_bottom`、`wp_path_max_width`、`qss_*`×17）。
- **字节级验证**：明/暗 × 毛玻璃/非毛玻璃 4 组合渲染输出与 HEAD 逐字节相等
  （offscreen QApplication 实测 `==` 全 True）。

### 3. 白名单收窄

`scripts/audit_styles.py` WHITELIST 删除 `core/theme/qss_dark.py`、`core/theme/qss_light.py`，
仅保留 `core/theme/tokens.py`、`ui/widgets.py`、`scripts/audit_styles.py`（`tests/` 由
`audit_file()` 内 `rel.startswith("tests/")` 恒豁免）。

### 4. 孤儿键决策（T8 遗留）

| 键 | 决策 | 依据 |
|---|---|---|
| `rss_hint_padding` | **保留** | `dialogs/f.py:88` 活跃引用（T8 评审 C2 修复） |
| `rss_grid_color` | 删除 | 全仓零引用（仅 tokens.py / test_style_tokens.py / 根 task-8-report.md） |
| `rss_header_bg` | 删除 | 同上 |
| `rss_header_border` | 删除 | 同上 |
| `rss_menu_item_hover` | 删除 | 同上 |
| `rss_panel_card` | 删除 | 同上 |
| `rss_sel_bg` | 删除 | 同上 |

同步从 `tests/test_style_tokens.py` `_PALETTE_KEYS` 移除 6 个孤儿键、登记 30 个 `qss_*` 键。

## 审计结果

- `python scripts/audit_styles.py --init`：**0 violations**（基线 20 → 0，含 T8 遗留
  `f.py:88` 陈旧条目自然消失）。
- `python scripts/audit_styles.py --check`：`OK: 0 violations, none new vs baseline`（exit 0）。
- 白名单 == 最小集（4 项）。

## 测试

- 样式护栏全绿：`test_style_guardrails.py` / `test_style_tokens.py` / `test_style_audit.py` /
  `test_style_audit_exempt.py` / `test_theme_borders.py` / `test_tray_menu.py` /
  `test_style_widgets.py` → **36 passed**。
- 全量 `pytest tests/ -q`：**528 passed, 1 failed**——唯一失败
  `test_module_page_smoke_no_crash_subprocess` 为已知环境问题（B008：子进程
  PySide6 `DLL load failed while importing QtWidgets` 0xc0000139，与本次改动无关；
  `test_sysinfo` 剪贴板用例在崩溃子进程后偶发 flaky，单独运行通过）。
- 渲染回归：`test_tray_menu.py` 断言 `min-height: 20px` / `padding: 3px 24px 3px 12px`、
  `test_theme_borders.py` 断言 `padding: 0 8px` 均保持（scale 1.0 字节不变）。

## 提交

- `refactor(style): qss 兜底收敛至 theme_palette 引用 + 豁免收窄至最小集；baseline 20→0`
  - 13 files changed（tokens.py、qss_dark.py、qss_light.py、audit_styles.py、
    styles_audit_baseline.json、7 个 size_literal 文件、test_style_tokens.py）+ 本报告。

## 偏差记录

- Brief Step 4 的 `git add` 清单仅列 4 个 qss/audit 文件；实际任务范围含 19 处
  size_literal 迁移与孤儿键决策，故提交包含全部 13 个改动文件。
- Brief 未预列 `qss_checkbox_disabled` 键：亮色 `text_disabled` 为 `rgba(0,0,0,0.30)`，
  与原 qss 亮色 `QCheckBox:disabled` 的 `0.35` 不等，新增专用键保字节一致。
- 明/暗全套截图人工确认：本任务全部改动为"值不变仅改来源"（字节级验证覆盖），
  无视觉退化风险；截图步骤省略。