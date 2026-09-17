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

## 测试规范（强制）

> 详细根因分析、正反例代码见 `docs/测试编写规范.md`。

1. **测试模块顶层禁止副作用**：不得在 import 时写环境变量、创建 QApplication、
   读写文件/DB、注册全局对象。所有初始化放 fixture。
2. **`QT_QPA_PLATFORM` 只允许 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`**。
   禁止直接赋值（会劫持整个 pytest 会话）。需要真实窗口平台的测试必须独立进程运行，
   并从主套件 `--ignore`。
3. **QApplication 只在 `tests/conftest.py` 的 session fixture 创建**，测试文件通过参数
   注入获取，禁止模块顶层 `QApplication(...)`。
4. **fixture 只清理自己创建的对象**。禁止遍历 `QApplication.allWidgets()` 做类型过滤清理。
5. **依赖交互式桌面的测试必须守卫**：
   `@pytest.mark.skipif(bool(os.environ.get("CI")), reason="requires interactive desktop session")`。
   必须包 `bool()`（裸字符串条件会被 pytest `eval()` → `NameError`）。
6. **路径计算必须跨盘符安全**：`os.path.relpath(path, REPO)` 在两者不同盘符时抛
   `ValueError`（CI 工作区在 `D:`、`tmp_path` 在 `C:`）。必须 try/except 回退。
   回归测试用 monkeypatch 把 REPO 指到别的盘符来模拟 CI。
7. **持久化资源必须隔离**：新增 store/DB/配置文件时同步加入 `tests/conftest.py`
   的 `_isolate_db` autouse fixture，重定向到 `tmp_path`。
8. **手工 patch 模块全局必须成对还原**（优先用 `monkeypatch` fixture）。
9. **已知崩溃路径（0xC0000005）用父子进程隔离**（参考 `tests/test_todo_notes_ui.py`
   的 `_YZ_SUBPROCESS_CHILD=1` 模式）。
10. **新增测试文件必须加入 `.github/workflows/python-app.yml` 的 4 个 chunk 文件列表**，
    否则 CI 不会运行它（列表是显式枚举，不是自动发现）。
11. **本地提交前**：`python scripts/audit_styles.py --check` 与相关测试必须通过。