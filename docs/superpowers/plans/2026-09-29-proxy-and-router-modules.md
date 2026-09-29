# 实施计划：proxy_ctrl + router_admin

- 规格：[proxy_ctrl](../specs/2026-09-29-proxy-ctrl-design.md) / [router_admin](../specs/2026-09-29-router-admin-design.md)
- 用户已授权免审批直接实施（2026-09-29：「开始你的工作吧 直到把所有功能实现前 不要问我」）
- 状态图例：`[ ]` 未开始 `[~]` 进行中 `[x]` 完成

## 波次划分

每个波次内的任务文件集不相交，逻辑上可独立推进；跨波次有依赖（测试先于实现）。

- **W1 传输/解析层**（router）：`telnet.py` `parsers.py` — 无前置依赖
- **W2 扫描/测速层**（proxy）：`scanner.py` `speedtest.py` — 无前置依赖
- **W3 配置层**（proxy + router）：`envstore.py` `targets.py` `config_editor.py` `services.py` `wifi.py` — 依赖 W1（telnet 句柄）
- **W4 存储层**：`store.py` ×2 `backup.py` `collectors.py` `connection.py` — 依赖 W1/W3
- **W5 UI 层**：`widgets/*` `workers.py` `module.py` ×2 — 依赖 W2/W3/W4
- **W6 集成验证**：CI 登记、全量测试、样式审计、真机冒烟

---

## W1 router 传输/解析层

- [ ] T1 `tests/test_router_telnet.py`（先红）
- [ ] T2 `tests/test_router_parsers.py`（先红，fixture 用真实探测输出）
- [ ] T3 实现 `modules/router_admin/telnet.py`
- [ ] T4 实现 `modules/router_admin/parsers.py`

## W2 proxy 扫描/测速层

- [ ] T5 `tests/test_proxy_scanner.py`（先红）
- [ ] T6 `tests/test_proxy_speedtest.py`（先红）
- [ ] T7 实现 `modules/proxy_ctrl/scanner.py`
- [ ] T8 实现 `modules/proxy_ctrl/speedtest.py`

## W3 配置层

- [ ] T9 `tests/test_proxy_envstore.py`（先红）
- [ ] T10 `tests/test_proxy_targets.py`（先红）
- [ ] T11 `tests/test_router_services.py`（先红）
- [ ] T12 `tests/test_router_config.py`（先红）
- [ ] T13 实现 `modules/proxy_ctrl/envstore.py`
- [ ] T14 实现 `modules/proxy_ctrl/targets.py`
- [ ] T15 实现 `modules/router_admin/services.py`
- [ ] T16 实现 `modules/router_admin/wifi.py`
- [ ] T17 实现 `modules/router_admin/config_editor.py`

## W4 存储层

- [ ] T18 `tests/test_router_collectors.py`（先红）
- [ ] T19 实现 `modules/proxy_ctrl/store.py`
- [ ] T20 实现 `modules/router_admin/store.py`（DPAPI 口令）
- [ ] T21 实现 `modules/router_admin/backup.py`
- [ ] T22 实现 `modules/router_admin/connection.py`
- [ ] T23 实现 `modules/router_admin/collectors.py`

## W5 UI 层

- [ ] T24 实现 `modules/proxy_ctrl/widgets/{tables,home_widget,page}.py`
- [ ] T25 实现 `modules/proxy_ctrl/{module,__init__}.py`
- [ ] T26 实现 `modules/router_admin/workers.py`
- [ ] T27 实现 `modules/router_admin/widgets/{tabs_overview,tabs_clients,tabs_services,tabs_config}.py`
- [ ] T28 实现 `modules/router_admin/widgets/{page,home_widget}.py`
- [ ] T29 实现 `modules/router_admin/{module,__init__}.py`
- [ ] T30 `tests/test_proxy_ui.py`（先红再绿）
- [ ] T31 `tests/test_router_ui.py`（先红再绿）

## W6 集成验证

- [ ] T32 把 7 个新测试文件登记进 `.github/workflows/python-app.yml` 的 4 个 chunk
- [ ] T33 `python -m pytest tests/test_proxy_*.py tests/test_router_*.py -v` 全绿
- [ ] T34 `python -m pytest -q` 全量无回归
- [ ] T35 `python scripts/audit_styles.py --check` 无新增违规
- [ ] T36 `pytest tests/test_style_guardrails.py -v` 通过
- [ ] T37 真机冒烟（一次性人工，不进 CI）
- [ ] T38 conventional commit

---

## 关键技术决策备忘

1. **纯逻辑层零 Qt**：`scanner.py` `parsers.py` `telnet.py` `targets.py` `envstore.py` `config_editor.py` `services.py` `speedtest.py` 一律不 import PySide6 → 可在无 QApplication 下跑。
2. **结束标记**：`run` 命令后追加 `; echo "__YZP_<uuid>__"`，按 uuid 精确切分输出，杜绝跨命令串扰。
3. **`/proc/stat` 首行**用 `cat /proc/stat` 整体取回后取首行（不依赖 `head` applet）。
4. **命令注入防线**：服务名 `^[A-Za-z0-9_.-]+$` 白名单；配置路径白名单 6 项；危险键前置拦截。
5. **Wi-Fi 回滚**：先在远端起 `nohup sh -c 'sleep 45; wifi up' &` 解绑定回滚，再执行关闭；标记文件 `/tmp/yzp_wifi_rollback` 用于定位与终止。
6. **口令**：DPAPI（`win32crypt`）加密存 JSON，解密失败要求重填，不降级明文。
7. **文件行数**：每文件 ≤ 250 行；`page.py` 允许单函数原子切片（参照 `perf_monitor/page.py` 既有约定 + 文件头注明）。
