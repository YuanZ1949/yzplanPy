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
- 剩余 20 处均为白名单文件（`core/theme/tokens.py`、`core/theme/qss_dark.py`、
  `core/theme/qss_light.py`、`ui/widgets.py`、`scripts/audit_styles.py`）内的令牌定义本身。

## 测试

- 新增护栏 C：`test_rss_palette_subset_of_theme_palette`（`tests/test_style_guardrails.py`）——
  断言 `rss_palette()` 键集 ⊆ `theme_palette()` 且逐项值一致。
- 修复测试污染：`test_style_guardrails.py::_force_dark` 原 patch `resolve_dark` 后不还原，
  导致同进程后续 `test_theme_refresh_qss_child` 在浅色下仍取暗色板（`#e8e8e8`）。
  新增 `_restore_dark()` 并在测试 `finally` 中还原，双 patch（`core.theme.base` + `core.theme`）一致。
- 8 文件全量：**96 collected, 96 passed**（含 guardrails 先行的原失败顺序）。
- `pytest tests/test_style_guardrails.py -v`：3 passed。

## 提交

- `f0b8c64 refactor(style): rss_aggregator theme tokens migration, baseline 169->20`
- 27 files changed, 533 insertions(+), 1293 deletions(-)

## 偏差记录

- 评审 Brief 中给出的 `def _rss_colors()` 私有调色板示例与 AGENTS.md 规则 4（禁止私有调色板）
  冲突，未采纳；改为 Approach B（并入全局 `theme_palette()`），并在护栏 C 中固化约束。