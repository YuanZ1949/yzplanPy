# Task 8 报告：rss_aggregator 主题令牌迁移

## 目标

将 `modules/rss_aggregator` 全部硬编码样式（hex 颜色、固定像素尺寸、私有调色板）迁移到
`core.theme.tokens.theme_palette()` / `sizing()` 令牌体系，审计违规基线从 169 降至 20，
并保证主题切换动态刷新回归测试全绿。

## 方案（Approach B）

- 所有 `rss_*` 颜色键并入 `core/theme/tokens.py` 的 `theme_palette()` 明暗两套分支，
  值与原 `_rss_colors()` 逐字节一致（零视觉变化）。
- `text_utils.rss_palette()` / `rss_panel_palette()` 改为 `dict(theme_palette())` 子集视图；
  `rss_style_vars()` = `rss_palette()` + `sizing()` 合并。
- 尺寸/字号全部走 `sizing()` 的 `rss_*` 令牌（随字体缩放 0.7~1.6 实时同步）。
- 删除模块私有调色板 `_rss_colors()` / `_rss_panel_colors()`。

## 迁移文件（20 个调用点）

`styles.py`、`page.py`、`page_preview.py`、`page_toolbar.py`、`page_theme.py`、
`page_layout.py`、`page_lifecycle.py`、`page_grips.py`、`home.py`、`page_batch.py`、
`page_torrent.py`、`rows.py`、`rows_item.py`、`sidebar.py`、`sidebar_data.py`、
`dialogs/f.py`、`dialogs/e.py`、`text_utils.py`、`page_context.py`、`page_settings_build.py`、
`sidebar_actions.py`、`dialogs/a.py`、`dialogs/b.py`、`__init__.py`。

## 审计结果

- `scripts/audit_styles.py --init` 重建基线：**20 处违规**（`scripts/styles_audit_baseline.json`）。
- `scripts/audit_styles.py --check`：`OK: 20 violations, none new vs baseline`。
- 剩余 20 处**并非**白名单文件内的令牌定义，而是分布在 8 个非白名单文件中的
  `size_literal` 违规（评审 C1 纠正，原报告误述为"均为白名单文件"）：

  | 文件 | 行 | 规则 |
  |---|---|---|
  | `core/tray/dialogs.py` | 72, 73, 75 | size_literal |
  | `core/tray/tray_base.py` | 125, 126 | size_literal |
  | `modules/rss_aggregator/dialogs/f.py` | 88 | size_literal |
  | `modules/screenshot/screenshot_ui.py` | 113, 142 | size_literal |
  | `modules/todo_notes/home.py` | 110, 111, 112, 120, 122, 123, 124 | size_literal |
  | `ui/home_tab/picker.py` | 17, 22 | size_literal |
  | `ui/settings_tab/mcp.py` | 42 | size_literal |
  | `ui/settings_tab/rows.py` | 14, 46 | size_literal |

  其中唯一属于 rss_aggregator 的 `dialogs/f.py:88`（`padding: 8px 4px`）已在评审
  修复中接入 `sizing()['rss_hint_padding']`（值同为 `8px 4px`，随字体缩放），
  **rss_aggregator 现为零违规**。修复后剩余 **19 处**，全部为上述 7 个非 rss 文件
  的既有 `size_literal`（属后续任务范围，非本任务）。

## 测试

- 新增护栏 C：`test_audit_private_palette_rule_catches_rss_style_defs`
  （`tests/test_style_guardrails.py`）——回归锁定审计 `private_palette` 规则本身：
  构造 `def _rss_palette_colors():` 私有调色板定义，断言 `audit_file()` 必捕获。
  （评审 I3：原 `test_rss_palette_subset_of_theme_palette` 是同义反复——
  `rss_palette()` 字面返回 `dict(theme_palette())`，断言恒真，已替换。）
- 修复测试污染（评审 I1）：`_force_dark` / `_restore_dark` / `_ORIG_RESOLVE_DARK`
  双 patch 辅助统一上移到 `tests/conftest.py` 共享（零重复），
  `test_style_guardrails.py` / `test_style_widgets.py` / `test_style_tokens.py` /
  `test_todo_sysinfo_style.py` 全部改为 `from conftest import ...` 并在 `finally`
  中 `_restore_dark()` 还原，杜绝泄漏的 `resolve_dark` patch 污染同进程后续
  主题切换回归（`#e8e8e8` 事故）。
- `_PALETTE_KEYS` 扩展 67 个 `rss_*` 键（评审 I3），明暗两套存在性测试全覆盖；
  并加自校验：调色板新增 `rss_*` 键未登记进 `_PALETTE_KEYS` 即失败（防静默漏检）。
- 验证（评审修复后实测）：
  - `pytest tests/test_style_widgets.py tests/test_rss_theme_refresh.py -v`：8 passed
    （原失败顺序，`test_theme_refresh_qss_child` 不再取错色板）
  - 反向顺序：8 passed
  - `pytest tests/test_style_guardrails.py tests/test_style_tokens.py tests/test_style_widgets.py tests/test_todo_sysinfo_style.py -v`：19 passed
  - `pytest tests/test_rss.py tests/test_rss_theme_refresh.py -v`（rss 冒烟）：24 passed
  - `python scripts/audit_styles.py --check`：`OK: 19 violations, none new vs baseline`（exit 0）

## 提交

- `f0b8c64 refactor(style): rss_aggregator theme tokens migration, baseline 169->20`
  - 27 files changed, 533 insertions(+), 1293 deletions(-)
- 评审修复提交见下节。

## 评审修复记录（Rejected → 修复）

| 发现 | 级别 | 修复 |
|---|---|---|
| C2 rss 归零未达成（`dialogs/f.py:88` `padding: 8px 4px`） | Critical | 接入 `sizing()['rss_hint_padding']`（复用既有令牌，值 `8px 4px`），rss 审计归零 |
| C1 报告构成失实（20 处误述为白名单文件） | Critical | 本报告"审计结果"节改为真实 file:rule 明细（修复后 19 处、0 rss） |
| I1 测试污染修复不完整（3 文件泄漏 `resolve_dark` patch） | Important | 辅助上移 `tests/conftest.py` 共享，4 文件统一 try/finally 还原 |
| I3 护栏同义反复 + `_PALETTE_KEYS` 未扩展 | Important | 替换为审计规则回归测试；`_PALETTE_KEYS` 扩展 67 个 `rss_*` 键 + 自校验 |

## 偏差记录

- 评审 Brief 中给出的 `def _rss_colors()` 私有调色板示例与 AGENTS.md 规则 4（禁止私有调色板）
  冲突，未采纳；改为 Approach B（并入全局 `theme_palette()`），并在护栏 C 中固化约束。
- 7 个零引用 `rss_*` 键（`rss_grid_color`/`rss_header_bg`/`rss_header_border`/
  `rss_hint_padding`/`rss_menu_item_hover`/`rss_panel_card`/`rss_sel_bg`）保留不删，
  由控制器在 T9 白名单最小化时决策（其中 `rss_hint_padding` 已被 C2 修复引用）。