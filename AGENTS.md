# YZplan 开发协作规范

本文件约束本项目中的所有代码变更（人类开发者与 AI 代理一致遵守）。

## GUI 样式规则（强制）

1. **新控件必须从 `ui/widgets.py` 工厂创建**（`make_button` / `make_line_edit`
   / `make_combo` / `make_card` / `make_status_chip` / `make_label`）。
   禁止手动 `setFixedHeight(数字)` + `setStyleSheet(硬编码)`。

2. **颜色必须来自 `core.theme.tokens.theme_palette()`**。禁止书写 hex 字面量
   （如 `#ff0000`）与 rgba 字面量。需要新色时先在 `theme_palette()` 中新增 key。

3. **字号/尺寸必须来自 `core.theme.tokens.sizing()`**。禁止 `font-size: 13px`、
   `padding: 5px 14px` 等手写像素值。全部以 `sizing()` 返回的令牌为准，
   尺寸会自动随字体缩放（0.7~1.6）同步，避免截断。

4. **模块禁止私有调色板**：不得定义 `_xxx_colors()` / `_theme_colors()`。
   模块样式函数一律接收 `theme_palette()` 返回的 dict 作为参数。

5. **修改样式前先改令牌**：若某控件需要新尺寸或新颜色，先在 `tokens.py`
   确认/新增对应令牌，再在工厂或样式函数中引用。禁止绕过令牌直接写值。

6. **增量迁移门槛**：每次改动后运行
   `python scripts/audit_styles.py --check`（新增违规即失败）与
   `pytest tests/test_style_guardrails.py -v`（主题切换无残留、1.6x 无截断）。

## 通用规范

- 模块间通信走定义良好的接口；单文件超过 250 行需拆分。
- 提交信息遵循 conventional commits（`feat/fix/refactor/docs/perf/test`）。
- 本仓库 TDD：先写失败测试，再实现，再提交。