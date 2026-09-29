# 路由器状态监测与管理模块（router_admin）设计规格

- 日期：2026-09-29
- 目标设备：小米「小胖」路由器（XiaoQiang），OpenWrt 底子
- 连接参数：192.168.2.1:23，telnet，用户 `root`，口令见配置
- 形态：YZplan 新模块 `modules/router_admin/`，独立可开关

## 1. 目标与非目标

### 目标

1. **状态监测**：系统资源、网络接口、在线终端、关键进程、WAN 状态。
2. **管理**：四类写操作——服务启停、Wi-Fi 开关/重启无线、改配置并重启系统、改配置并重启相关服务。

### 非目标

- 不做 Web 后台（192.168.2.1 的 LuCI 等价物）。
- 不做流量统计持久化历史库（只做当前值 + 会话内趋势）。
- 不做固件升级。
- 不做桥接/VLAN/端口转发等复杂网络拓扑编辑（只做既有配置项的键值编辑）。

## 2. 设备实测基线（探测于 2026-09-29）

| 项 | 实测值 | 设计影响 |
|---|---|---|
| 系统 | BusyBox v1.25.1 (ash)，`XiaoQiang login:` | 提示符是 `root@XiaoQiang:~#`，登录后需等 MOTD 打完 |
| 内核 | Linux 4.4.60 armv7 | `/proc` 齐全 |
| CPU | 2 × ARMv7 Cortex-A7 (part 0x801) | — |
| 内存 | MemTotal 182868 kB，MemFree ~27 MB | 内存卡片用 `/proc/meminfo` |
| 运行时间 | `/proc/uptime` 可读 | 需处理小数秒 |
| WAN | `pppoe-wan` inet 100.64.159.39/32，peer 100.64.159.1 | **CGNAT，无公网 IPv4**；IPv6 全局地址可读 |
| LAN | `br-lan` 192.168.2.1/24、`br-miot` 192.168.32.1/24 | 终端发现分两段 |
| 流量 | `/proc/net/dev` 有 rx/tx bytes+packets+errs+drop | 每接口流量卡片；两次采样算速率 |
| 在线终端 | `/proc/net/arp` 20 条，flags 0x2=完整 | 完整项 = 在线；配合 dnsmasq 租约取主机名 |
| 服务 | `/etc/init.d` 存在 | 启停走 `/etc/init.d/<name> <action>` |
| ubus | `ubus` CLI 在，ubusd 进程在 | 可作为可选增强，**不作为主路径**（主路径只用 `/proc` + 基础命令，兼容性最好） |
| ICMP | 被墙（`PingSucceeded: False`） | 一切健康判断基于 telnet 往返，不基于 ping |
| CPU 占用 | `ps` 无 CPU% 列 | 改用 `/proc/stat` 两次采样差值算占用率；`/proc/loadavg` 作为原始负载一并展示（可读时） |

**探测约定**：本规格的探测阶段只跑只读命令；`probe_router.py` 与 `router_probe.log` 已删除，工作树干净。

## 3. 架构

```
UI 层        widgets/home_widget.py, widgets/page.py, widgets/tabs.py, module.py
             只渲染与派发；连接/采集/写操作全部经 QThread
    │
操作层       client.py（telnet 会话）、services.py（服务）、wifi.py（无线）、
             config_editor.py（配置编辑+备份+重启）、backup.py（本地存档）
    │
采集层       collectors/*.py（各指标一个纯函数：命令串 → 结构化数据）
             **不 import PySide6**，不持有连接，只吃文本
    │
传输层       telnet.py（裸 socket 会话：登录/发命令/读输出/断连）
```

关键分层理由：**采集层是纯函数**（输入命令输出文本，输出 dict），所以可以用真实探测时抓到的输出做 fixture 离线单测，不需要连真机。

## 4. 文件清单

```
modules/router_admin/
  __init__.py
  module.py            MODULE_INFO + Module(ModuleBase)；start/stop 管轮询定时器
  connection.py        RouterConnection 参数校验 + 默认值
  telnet.py            裸 socket telnet 会话（登录/执行/读标记/关闭）
  parsers.py           纯文本 → 结构化数据（可注入，无连接依赖）
  collectors.py        组装采集命令串 + 调用 parsers
  services.py          /etc/init.d 列表解析 + 启停命令构造
  wifi.py              无线状态读取 + 开关/重启命令构造 + 回滚计划
  config_editor.py     /etc/config 解析/编辑/写回 + 备份 + 生效方式
  backup.py            远程配置备份到本地 <DATA_DIR>/router_admin/backups/
  store.py             连接参数与 UI 偏好持久化
  workers.py           QThread worker 封装（采集/写操作）
  widgets/
    __init__.py
    home_widget.py
    page.py
    tabs_overview.py    系统/网络总览
    tabs_clients.py     在线终端
    tabs_services.py    服务管理
    tabs_config.py      配置编辑
tests/
  test_router_telnet.py
  test_router_parsers.py
  test_router_services.py
  test_router_config.py
  test_router_collectors.py
  test_router_ui.py
```

## 5. 传输层：`telnet.py`

裸 socket（`requirements.txt` 无 telnet 库）。

```python
class TelnetSession:
    def __init__(self, host, port=23, user="root", password="",
                 connect_timeout=8.0, read_timeout=12.0): ...
    def open(self) -> None          # 连接 → 等 login → 发 user → 等 Password → 发 password → 等提示符
    def run(self, command, *, timeout=None) -> str   # 发送 + 读到结束标记
    def run_batch(self, commands: list[str], *, timeout=None) -> list[str]  # 单连接多命令
    def close(self) -> None
```

协议细节：

- **结束标记**：每条命令后追加 `; echo "__YZP_<8位uuid>__"`（OpenWrt 的 `echo` 是 busybox applet，可用）。读到该标记即认为输出结束，标记本身从结果中剔除。用 uuid 保证同一次会话内不重复，杜绝「上一条命令残留输出被当成下一条结果」。
- **IAC 处理**：过滤 telnet 协议字节（`0xFF` 起的转义序列），只保留可打印字符；不做 IAC 协商应答（BusyBox telnetd 对裸连接不发协商请求即可工作，已在探测中验证）。
- **提示符识别**：登录后按 `root@XiaoQiang:~#` 结尾判定就绪；同时容忍 `BusyBox` MOTD ASCII art（读到提示符才算完）。
- **编码**：全程 `utf-8`，`errors="replace"`。
- **关闭**：显式 `close()`，`__exit__` 兜底；socket 设 `SO_LINGER` 避免 TIME_WAIT 堆积。

`run_batch` 是轮询性能的关键——一次连接取全部指标，而不是每项指标开一次连接。

## 6. 采集层：`parsers.py`（纯函数，全部可离线单测）

| 函数 | 输入 | 输出 |
|---|---|---|
| `parse_uptime(text)` | `/proc/uptime` | `{"uptime_s": float}` |
| `parse_meminfo(text)` | `/proc/meminfo` | `{"total_kb","free_kb","available_kb","cached_kb","slab_kb","used_pct"}` |
| `parse_proc_stat(text, prev)` | 两次 `/proc/stat` 采样 | `{"cpu_pct": float}`；`prev is None` 时返回 `None` |
| `parse_loadavg(text)` | `/proc/loadavg` | `{"load1","load5","load15"}`；不可读时 `None` |
| `parse_net_dev(text)` | `/proc/net/dev` | `[{"iface","rx_bytes","tx_bytes","rx_pkt","tx_pkt","errs","drop"}]` |
| `parse_ifconfig(text)` | `ifconfig` 输出 | `[{"iface","inet","netmask","mac","mtu","hwaddr_hwtype"}]` |
| `parse_arp(text)` | `/proc/net/arp` | `[{"ip","mac","dev","complete"}]`（flags 末位 == 2 判完整） |
| `parse_dnsmasq_leases(text)` | 租约文件 | `[{"mac","ip","hostname","expires"}]` |
| `parse_ps(text)` | `ps` 输出 | `[{"pid","comm","args"}]` + `count` |
| `parse_df(text)` | `df -k` | `[{"mount","total_kb","used_kb","avail_kb","use_pct"}]` |
| `parse_uptime_fmt(seconds)` | 数值 | `"3 天 4 时 5 分"` |
| `merge_clients(arp, leases)` | 两者 | 按 IP 关联，**优先 dnsmasq 主机名**，无租约的仍列出（MAC 兜底） |

**采集命令串**（`collectors.py` 拼装，一次 `run_batch` 取完）：

```
cat /proc/uptime
cat /proc/meminfo
cat /proc/loadavg
cat /proc/stat | head -1
cat /proc/net/dev
ifconfig
cat /proc/net/arp
cat /tmp/dnsmasq.leases      # 探测未确认存在 → 缺失时降级
ps
df -k
```

租约路径探测时未确认，故 `collectors` 内置候选列表 `[/tmp/dnsmasq.leases, /var/etc/dnsmasq.leases, /tmp/dnsmasq.leases.hosts]`，用 `cat A B 2>/dev/null` 一次取回，取不到就返回空列表而非报错。

**CPU 占用率**：`/proc/stat` 首行 `cpu  user nice system idle iowait ...` 为累计 jiffies。两次采样差值 `Δtotal`、`Δidle` → `cpu_pct = 100 × (1 - Δidle/Δtotal)`。首屏无历史时显示 `--`，第二次刷新后出值。`/proc/loadavg` 存在则一并展示原始负载——对无线 SoC 而言 loadavg 往往比 cpu_pct 更有参考价值。

## 7. 管理操作

### 7.1 服务启停（`services.py`）

- 列服务：`ls /etc/init.d` + 逐个 `test -x /etc/init.d/<n> && echo <n> ON || echo <n> OFF`，或 `ls -1 /etc/init.d`
- 动作：`/etc/init.d/<name> <start|stop|restart>`，`sh -c` 包一层
- **服务名白名单校验**：仅允许 `^[A-Za-z0-9_.-]+$`，拒绝任何含 `/` `..` `;` `` ` `` `$` 的名字（命令注入防线）
- 已知危险服务（`network` `firewall` `dnsmasq` `netifd` `pppd` `odhcpd` `uhttpd`）在 UI 标红并要求二次确认

### 7.2 Wi-Fi 开关 / 重启无线（`wifi.py`）

- 读状态：`ifconfig wl0` + `ifconfig wl1` 是否有 inet；`ps | grep hostapd` 是否在
- 动作：
  - 开：`wifi up`
  - 关：`wifi down`
  - 重启无线：`/etc/init.d/network restart`（会短暂断链）或 `wifi down && sleep 2 && wifi up`
- **断连自恢复（关键安全机制）**：`wifi down` 会切断我们自己的 telnet（telnet 走 br-lan，但 hostapd 停掉后 AP 消失，无线客户端失联）。因此：
  1. 关闭/重启前，先在 `telnet` 上启动**一次性回滚**：`sleep 45; wifi up`（用 `nohup ... &` 与当前 shell 解绑），并把回滚时刻显示在 UI 上；
  2. 60 秒内用户若未点「我已恢复连接」，回滚自动执行；
  3. 用户成功重连后点「取消回滚」，则发 `kill` 掉那个回滚进程。
  - 回滚命令用 `pgrep -f 'sleep 45'` 或写入 `/tmp/yzp_wifi_rollback` 标记文件来定位并终止，避免误杀。

### 7.3 配置编辑 + 生效（`config_editor.py`）

- 读取：`cat /etc/config/<section>`，按 UCI 语法解析成 `{section_type: {section_name: {key: value}}}`
- 编辑：UI 呈现「section → key → value」三列表单，值改动后 diff 预览
- 写回：**先备份**（见 7.4），再整文件写回
- 生效方式（用户选）：
  - 只重载相关服务（`/etc/init.d/<svc> restart`）
  - 整系统重启（`reboot`）
- **允许编辑的路径白名单**：`/etc/config/network`、`/etc/config/dhcp`、`/etc/config/firewall`、`/etc/config/wireless`、`/etc/config/system`、`/etc/config/dnsmasq`。其他路径不出现在 UI 里。
- **危险键拦截**：写回前扫描，命中以下任一则拒绝并列出键名：
  - `network` 的 `lan.ipaddr` 改成非当前子网的地址（会导致自己失联）
  - `wireless` 的 `disabled` 置 0（开启无线）需二次确认
  - `firewall` 的 `option input` 从 `ACCEPT` 改成其他
  - 任何 `root` 密码 / `passwd` 字段
- 写回用 `cat > file <<'EOF' ... EOF` 单次原子写入（OpenWrt 的 `mv` 可能跨文件系统，故先 `write` 临时文件再 `mv`，同目录保证原子）。

### 7.4 配置备份（`backup.py`）

- 每次写回**前**自动：`cat /etc/config/X > /tmp/yzp_bk_X`，成功后 `cat /tmp/yzp_bk_X` 取回文本，存到本地 `<DATA_DIR>/router_admin/backups/<时间戳>_X`
- 保留最近 20 份
- UI 提供「历史备份」列表与「查看/还原」入口
- 本地备份是**读操作**，即使路由器已失联也能用来手工恢复

## 8. 连接与凭据（`store.py` / `connection.py`）

- 连接参数存 `<DATA_DIR>/router_admin/settings.json`：host/port/user/password/connect_timeout/read_timeout/auto_refresh/interval
- 口令在 JSON 中以 `win32crypt.CryptProtectData`（DPAPI，当前用户作用域）加密存储；解密失败（换机器/换用户）时回落到要求用户重填，**不静默降级为明文**
- 预填默认值：host `192.168.2.1`、port `23`、user `root`；口令首次运行由用户在设置面板输入
- UI 里口令字段用 `PasswordEchoOnEdit=False`，读取时显示掩码

## 9. 数据流

### 状态采集

```
用户点「刷新」或自动刷新到期
  → QThread: RouterWorker.fetch()
      ① TelnetSession.open()（失败 → 结构化错误：超时/认证失败/连接拒绝）
      ② run_batch(采集命令串)
      ③ parsers 逐项解析；单项解析失败只置该项为「—」，不整轮失败
      ④ close()
  → signal(ok, payload) 回 UI 线程
```

### 写操作

```
用户点动作
  → 危险动作先过二次确认对话框（QMessageBox）
  → QThread: 执行命令 → 取回验证输出
  → signal 回 UI，InfoBar 反馈 + 自动刷新状态
```

## 10. 错误处理

| 场景 | 行为 |
|---|---|
| telnet 连不上（ConnectionRefused） | 「无法连接 192.168.2.1:23」，附「检查网线/Wi-Fi」提示 |
| 登录超时 | 「登录超时」，附「路由器负载高时可能出现，稍后重试」 |
| 认证失败 | 「口令错误」，不重试（避免锁账号） |
| 采集轮某项命令无输出 | 该项显示「—」，其余正常；底部状态栏列出失败的命令名 |
| 会话中途断开 | 自动重连一次；再失败则停止自动刷新并提示 |
| 改配置命中危险键 | 拒绝写入，列出命中的键名与原因，不做任何远端改动 |
| 备份失败 | 中止写回 |
| Wi-Fi 操作后失联 | 回滚计时器兜底（见 7.2），UI 在断连前就显示回滚倒计时 |
| 写操作超时 | 明确报「命令超时，路由器可能无响应」，提示可用 telnet 手工确认 |

## 11. UI

### 首页小卡

- 连接状态点（绿=已连/灰=未连/红=失败）
- WAN 地址 + 在线终端数 + 内存占用率
- 「刷新」「打开」两个按钮
- 5 秒 QTimer（连接态时才真正拉数据），`destroyed` 停表

### 详情页（frameless，四个 Tab）

1. **总览**：卡片网格（运行时间、内存、负载、CPU 占用、WAN 地址、IPv6、在线终端数、进程数）+ 接口流量表（iface / RX / TX / 速率 / 错误丢包）
2. **终端**：`merge_clients` 结果表（IP / MAC / 主机名 / 所属网段 / 状态），2 秒自动刷新开关
3. **服务**：`/etc/init.d` 列表，每行 启/停/重启 三按钮 + 状态点；危险项标红并二次确认
4. **配置**：白名单 section 树 → 键值表单 → diff 预览 → 「写回并重启服务」/「写回并重启路由器」/「查看备份」/「还原备份」

刷新模型：**手动为主 + 自动刷新可开关**（默认 5 秒，范围 3~30）。关页即断连，不留后台连接。

## 12. 样式与令牌合规

同 proxy_ctrl 规格第 9 节：无新控件工厂则先在 `ui/widgets.py` 新增并补测试；颜色只取 `theme_palette()`；尺寸只取 `sizing()`；无模块私有调色板；单文件 ≤ 250 行（`page.py` 允许「单函数原子切片」豁免，参照 `perf_monitor/page.py` 的既有约定，并在文件头注明）。

## 13. 测试

| 文件 | 覆盖 |
|---|---|
| `test_router_parsers.py` | 全部 11 个 parse 函数，用**真实探测输出**做 fixture；边界（无 /31 网卡、缺列、flags 非 0x2、df 无换行、uptime 小数） |
| `test_router_telnet.py` | 假 socket：登录序列、结束标记抽取、IAC 字节过滤、认证失败、超时、close 幂等 |
| `test_router_services.py` | 服务名白名单拒绝注入（`../../etc/passwd`、`a;reboot`、`a b`）；危险名单命中；启停命令串构造 |
| `test_router_config.py` | UCI 解析/序列化往返；危险键拦截（改 LAN IP、改防火墙 input、密码字段）；备份先于写回；路径白名单 |
| `test_router_collectors.py` | 命令串拼装含租约候选路径；`run_batch` 一次取全；单项解析失败不影响其余 |
| `test_router_ui.py` | offscreen：首页卡/详情页/四 Tab 构建；服务表与配置表填充 |

规则同 proxy_ctrl；`store.SETTINGS_PATH`、`backup.BACKUP_DIR` 必须 monkeypatch 到 `tmp_path`。

**不连真机的单测**：以上全部离线。真机只做**一次性人工冒烟**（见验收标准 5），不进 CI。

## 14. 验收标准

1. `python -m pytest tests/test_router_*.py -v` 全绿，且**不触碰 192.168.2.1**。
2. `python scripts/audit_styles.py --check` 无新增违规；`pytest tests/test_style_guardrails.py -v` 通过。
3. 全部新测试文件已登记进 CI 的 4 个 chunk 列表。
4. 真机冒烟（人工，一次性）：
   - 总览能显示运行时间/内存/负载/WAN IPv4+IPv6/在线终端数/接口流量；
   - `dnsmasq` 服务能 stop 再 start 并恢复正常；
   - 「改配置并重启服务」在 `dnsmasq` 的一个无害键上走通一轮，备份文件已落盘；
   - Wi-Fi 关闭时回滚计时器显示且能在 60 秒内自动恢复。
5. 扫描/写操作全程无明文口令落进日志或 UI 文本（除 DPAPI 密文）。
