# 代理控制模块（proxy_ctrl）设计规格

- 日期：2026-09-29
- 来源：`C:\MyFile\Desktop\toggle_proxy`（「全能代理管理器 v3.2」，作者 伊涅芙(Inev)，2026-04-18）
- 形态：YZplan 新模块 `modules/proxy_ctrl/`，独立可开关

## 1. 目标与非目标

### 目标

把 toggle_proxy 的 12 项功能完整移植为 YZplan 原生模块，含两部分：

1. **本机代理配置切换**——查看/启用/停用 git、curl、wget、docker、python、node、全局七类目标的代理；状态总览；可用性检测。
2. **局域网代理扫描器**——并发 TCP 探测 + 代理验证 + 测速排序 + 扫描结果落盘。

### 非目标

- 不保留 shell/PowerShell 脚本形态，不调用 `curl.exe` / `git bash`。
- 不实现原版 `status.ps1` 的「旧版串行扫描流程兼容」（已被三段式扫描器取代）。
- 不做代理自动选择（PAC）、不做多代理负载均衡。

## 2. 与原版的差异（有意为之）

| 项 | 原版 | 本模块 | 理由 |
|---|---|---|---|
| 环境变量写入 | `export` / `$env:x =`，仅当前进程 | 写 `HKCU\Environment` + `WM_SETTINGCHANGE` 广播 | 原版行为在 Windows 上等于无效（进程退出即失效） |
| 代理验证 | `curl.exe -x ... -w '%{http_code}'` | `requests` + `proxies=` | 已在 `requirements.txt`；跨平台 |
| TCP 并发上限 | 固定 150 / 20 | 默认 64 / 16，可配置 | Python 线程池下更保守的值；150 线程对 Windows 偏激进 |
| 扫描网段约束 | 无 | 必须落在私有地址段（10/8、172.16/12、192.168/16、127/8、169.254/16） | 防手滑填 `0.0.0.0/0` 造成事故 |
| 主机数上限 | 65536 | 65536（保留） | 同原版 |
| docker JSON 注入 | `jq '. + {"registry-mirrors": []}'`（注：注入了错误的 key） | 正确写/删 `proxies` 节点（`http-proxy` / `https-proxy`） | 原 bash 版是 bug；PS1 版正确，采用 PS1 语义 |
| python/node unset | 置空字符串 | 从注册表删除 | 空字符串会让部分工具误判为「已设置空代理」 |
| 测速 printf 残留 `N` | 有 | 无 | 原版 `speed_test.ps1` 的格式串 bug，不复刻 |

## 3. 架构

三层，依赖单向向下：

```
UI 层        widgets/home_widget.py, widgets/page.py, module.py
             只做渲染与事件转发；所有阻塞操作经 QThread 派发
    │
数据/操作层  scanner.py  speedtest.py  envstore.py  targets.py  store.py
             纯 Python + requests/socket/ctypes，**不 import PySide6**
    │
```

纯逻辑层可在无 QApplication 的环境下完整单测。

## 4. 文件清单

```
modules/proxy_ctrl/
  __init__.py          导出 Module / MODULE_INFO 与公共纯逻辑 API
  module.py            ModuleBase 子类 + MODULE_INFO；start/stop 无需定时器
  targets.py           七类代理目标的读/设/清矩阵
  envstore.py          HKCU\Environment 读写 + WM_SETTINGCHANGE 广播
  scanner.py           端口串解析、CIDR 展开、TCP 探测、代理验证
  speedtest.py         5 轮测速与评级
  store.py             扫描历史与记忆代理 URL 落盘
  widgets/
    __init__.py
    home_widget.py     首页精简卡片
    page.py            详情页
    tables.py          目标状态表 / 扫描结果表构建
tests/
  test_proxy_targets.py
  test_proxy_envstore.py
  test_proxy_scanner.py
  test_proxy_speedtest.py
  test_proxy_ui.py
```

## 5. 组件契约

### 5.1 `scanner.parse_port_range(spec) -> tuple[list[int], list[str]]`

- 分隔符 `[,\s]+`
- 段 `a-b`（`^\d+-\d+$`）展开为闭区间；**a > b 时自动纠正为 b..a**（不截断）
- 段 `^\d+$` 视为单端口
- 越界（<1 或 >65535）跳过并记入 warnings
- 返回 `(ports, warnings)`；ports 去重且**保持首次出现顺序**

### 5.2 `scanner.expand_cidr(cidr) -> tuple[int, int]`

- 正则 `^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:/(\d{1,2}))?$`
- 前缀缺省 24；> 32 钳到 32；< 0 报错
- 前缀 ≤ 30：排除网络号与广播地址（**不截断**，`/16` 全保留）
- `/31`、`/32`：保留全部地址
- 解析失败抛 `ValueError`；调用方负责回退默认网关 `/24`

### 5.3 `scanner.is_private_host(ip) -> bool`

判定是否落在 RFC1918 + 回环 + 链路本地。**扫描入口统一用它做前置校验**，不通过直接拒绝并返回明确原因。

### 5.4 `scanner.tcp_probe(hosts, ports, *, timeout, max_workers, cancel, on_progress) -> list[tuple[str,int]]`

- 笛卡尔积并发探测，`socket.create_connection`
- `cancel` 为 `threading.Event`，每轮检查
- `on_progress(done, total)` 回调
- 排除本机 IP

### 5.5 `scanner.verify_proxy(candidates, *, concurrency, target, cancel) -> list[ProxyCandidate]`

- 用 `requests.get(target, proxies={...}, allow_redirects=False, timeout=...)`
- **状态码必须 == 204** 才判定为真代理（防误报的核心规则，源自 `scanner_new.ps1`）
- 再试 `https://www.google.com/generate_204` 判定 `Mixed`（支持 CONNECT）/ `仅HTTP`
- `ProxyCandidate` 字段：`ip`、`port`、`latency_ms`、`kind`（`Mixed`/`仅HTTP`）、`scheme`

### 5.6 `speedtest.test_proxy_speed(url, *, rounds=5, target, timeout) -> SpeedResult`

- 仅 `2xx` 计入成功
- `avg = floor(sum/count)`
- 评级：`<100` 优秀 / `<300` 良好 / `<500` 一般 / 否则 较差
- 全失败时 `SpeedResult.ok is False` 且 `hints` 给出 3 条排查建议

### 5.7 `envstore`

```python
class RegistryBackend(Protocol):     # 测试替身注入点
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...   # 不存在须静默成功

def read_env(backend) -> str | None
def write_env(backend, name, value) -> None   # 写后广播
def unset_env(backend, name) -> None          # 不存在不报错
def broadcast_environment_change() -> bool    # SendMessageTimeoutW，超时 5s
```

`write_env` / `unset_env` 同时同步 `os.environ`，让**当前 YZplan 进程**立即生效。
删除不存在的值静默成功（`FileNotFoundError` → no-op）。

### 5.8 `targets` 目标矩阵

| id | 名称 | 读 | 设 | 清 |
|---|---|---|---|---|
| `git` | Git | `git config --global --get http.proxy` → 回退 `https.proxy` | 写两个 key | `--unset` 两个 key |
| `curl` | cURL | `http_proxy` / `https_proxy` | 写注册表 | 删除 |
| `wget` | wget | `WGET_PROXY` | 写注册表 | 删除 |
| `python` | Python | `http_proxy` / `https_proxy` | 写注册表 | 删除 |
| `node` | Node.js | `HTTP_PROXY` / `HTTPS_PROXY` | 写注册表 | 删除 |
| `global` | 全局 | 上列 curl+wget+node 合并 | 全部写入 | 全部删除 |
| `docker` | Docker | `daemon.json` 的 `proxies.http-proxy` | 增改 `proxies` 节点 | 删 `proxies` 节点 |

`ProxyTarget` 协议：`read() -> str`、`set(url) -> None`、`unset() -> None`。
`git` 目标通过 `subprocess.run` 调用 `git`；git 不存在时 `read()` 返回 `None` 并在 UI 标注「未安装」。

### 5.9 `store`

- 路径：`<DATA_DIR>/proxy_ctrl/history.json`
- 结构：`{"last_proxy_url": str, "scans": [{"ts": iso, "subnet": str, "results": [{ip,port,latency_ms,kind}]}]}`
- 保留最近 20 次扫描
- **测试必须通过 monkeypatch `store.STORE_PATH` 隔离**（AGENTS.md 规则 7）

## 6. 数据流

### 扫描

```
用户点「开始扫描」
  → page 组装 ScanParams（subnet/ports/timeout/concurrency）
  → QThread: scanner.scan(params, cancel, progress)
      ① 校验：is_private_host(subnet 的网络地址) 否则抛 ScanRejected
      ② expand_cidr → host 列表
      ③ tcp_probe（阶段一，progress(0,1)）
      ④ verify_proxy（阶段二，progress(1,2)）
      ⑤ 按 latency_ms 升序，评级
  → 结果落 store
  → signal 回 UI 线程，填表格
```

### 应用代理

```
用户点某目标「设置」
  → page 弹出 URL 输入（预填 last_proxy_url）
  → QThread: target.set(url)
  → InfoBar 反馈 + 刷新目标状态表
```

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| 网段非私有 | 拒绝，InfoBar 错误提示，给出具体网段 |
| 主机数 > 65536 | 拒绝并提示实际数量 |
| 端口串全非法 | 拒绝并列出 warnings |
| 端口全关闭 | 正常结束，提示「未发现开放端口」 |
| `git` 未安装 | 该目标显示「未安装」，其余目标不受影响 |
| `daemon.json` 解析失败 | 跳过该文件并警告，不写坏文件 |
| `daemon.json` 写入失败（需管理员） | 警告并提示所需权限 |
| 无可用候选 | 回落到手动输入 URL（复刻 `choose_proxy_url`） |
| 测速全失败 | 显示 3 条排查建议 |
| 扫描中取消 | 立即停止，保留已完成部分 |

## 8. UI

### 首页小卡（`create_home_widget`）

- 当前 HTTP 代理值（或「未设置」）
- 可用性圆点（绿/灰/红）
- 「打开」「切换」两个按钮
- 2 秒 QTimer 刷新（与 perf_monitor 首页一致），`destroyed` 时停表

### 详情页（`create_page`，frameless）

三段竖排，标题栏按钮放「导出历史」「打开数据目录」。

1. **目标状态表**：列 = 目标 / 当前值 / 状态 chip / 操作（设置·清除）。状态 chip 用 `make_status_chip`。
2. **全局操作条**：URL 输入 + 协议下拉（http/https/socks5）+ 「全部启用」「全部停用」「检测可用性」。
3. **扫描区**：参数行（网段、端口串、超时、并发）+ 开始/停止 + 进度条 + 结果表（IP:端口 / 延迟 / 类型 / 评级 / 操作：设为代理·测速）。

「检测可用性」逻辑沿用 `config.sh` 的 `check_proxy_availability`：空 URL 视为可用；否则 `requests.get("http://www.example.com", timeout=(2,5))`。

## 9. 样式与令牌合规

- 所有控件经 `ui/widgets.py` 工厂（`make_button`/`make_line_edit`/`make_combo`/`make_card`/`make_status_chip`/`make_label`）
- 表格样式函数接收 `theme_palette()` 返回的 dict 作为参数，**不定义 `_xxx_colors()`**
- 颜色取 `theme_palette()`；尺寸取 `sizing()`
- 需新增令牌时先改 `core/theme/tokens.py`（本模块预期零新增令牌）
- 单文件 ≤ 250 行

## 10. 测试

| 文件 | 覆盖 |
|---|---|
| `test_proxy_scanner.py` | `parse_port_range` 全形态（单值/多值/区间/反序区间/混合/非法/重复/越界）；`expand_cidr`（/24 /30 /31 /32 /16 /0 /前缀越界 /非法输入）；`is_private_host`；`tcp_probe`（假 socket、取消、进度回调）；`verify_proxy`（204 才算真代理、200/301 被拒、Mixed/仅HTTP 判定） |
| `test_proxy_envstore.py` | fake backend：读/写/删；删不存在静默；`os.environ` 同步；写入后触发广播 |
| `test_proxy_targets.py` | 七目标的 read/set/unset 契约（假 subprocess + 假 registry + 临时 json） |
| `test_proxy_speedtest.py` | 评级四档阈值；仅 2xx 计入；全失败分支含 hints |
| `test_proxy_ui.py` | offscreen：首页卡构建、详情页构建、目标表填充、扫描结果表填充 |

规则：`os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`；QApplication 只经 `qapp` fixture；`store.STORE_PATH` monkeypatch 到 `tmp_path`；新文件全部登记进 `.github/workflows/python-app.yml` 的 4 个 chunk。

## 11. 验收标准

1. `python -m pytest tests/test_proxy_*.py -v` 全绿。
2. `python scripts/audit_styles.py --check` 无新增违规。
3. `pytest tests/test_style_guardrails.py -v` 通过。
4. 在真实 Windows 上：`git` 目标设/清往返正确；`curl` 目标设后在**新开的 cmd** 里 `echo %http_proxy%` 能看到值（证明广播生效）。
5. 扫描器能在 `192.168.2.0/24` 上完成一轮三段式扫描并给出排序结果；对 `8.8.8.8/24` 之类的非私有网段**拒绝执行**。
6. 全部新文件已登记进 CI 的 4 个 chunk 列表。
