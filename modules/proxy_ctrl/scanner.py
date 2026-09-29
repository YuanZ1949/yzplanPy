"""局域网代理扫描器：端口串解析 → CIDR 展开 → TCP 探测 → 代理验证 → 排序。

移植自 toggle_proxy「全能代理管理器 v3.2」的 modules/scanner_new.ps1。纯
Python 数据层，不 import Qt，可在无 QApplication 环境下完整单测。

**防误报核心规则（源自原版，严禁放宽）**：经候选代理请求 generate_204 必须
**精确返回 HTTP 204**（EXPECTED_STATUS）才算真代理。普通 Web 服务器返回
200/301/404/403，被误认成代理就会把用户的 git 流量发给不相干的网站。

测试注入点（勿改名）：``_create_connection``、``_local_ips``、``requests``。
"""
import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import islice

import requests

DEFAULT_SUBNET = "192.168.2.0/24"
DEFAULT_PORTS = (7890, 10808, 3128, 8080, 80, 443)
DEFAULT_TARGET = "http://www.google.com/generate_204"
DEFAULT_HTTPS_TARGET = "https://www.google.com/generate_204"
MAX_HOSTS = 65536
#: generate_204 被正确转发时**必须**返回的状态码，其余一律判为非代理
EXPECTED_STATUS = 204
_PRIVATE_NETS = tuple(ipaddress.ip_network(n) for n in
                      ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                       "127.0.0.0/8", "169.254.0.0/16"))
_RE_CIDR = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:/(\d{1,2}))?$")
_RE_PORT = re.compile(r"^\d+$")
_RE_SPAN = re.compile(r"^(\d+)-(\d+)$")
_SPLIT = re.compile(r"[,\s]+")


class ScanRejected(Exception):
    """网段 / 规模 / 端口不合法。调用方直接提示用户，不重试。"""


@dataclass
class ProxyCandidate:
    ip: str
    port: int
    latency_ms: int
    kind: str  # "Mixed"（支持 CONNECT 隧道）/ "仅HTTP"
    scheme: str = "http"


def int_to_ip(value: int) -> str:  # 3232235777 → "192.168.2.1"，越界抛 ValueError
    return str(ipaddress.IPv4Address(int(value)))


def _parse_cidr(cidr: str) -> tuple[int, int, int]:
    """CIDR → (网络号, 地址数, prefix)。缺省 /24、>32 钳到 32、非法抛 ValueError。

    全程 32 位无符号整数运算（不走浮点），避免 /8 规模溢出。假设：正则只收无符
    号十进制，规格里的「前缀 < 0 报错」不可达，落到同一条「非法」分支抛 ValueError。
    """
    m = _RE_CIDR.match(str(cidr).strip())
    if not m:
        raise ValueError("不是合法 CIDR：%r" % (cidr,))
    octets = [int(g) for g in m.groups()[:4]]
    if any(o > 255 for o in octets):
        raise ValueError("IP 段越界（>255）：%r" % (cidr,))
    ip_int = (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
    prefix = min(int(m.group(5)) if m.group(5) else 24, 32)
    size = 1 << (32 - prefix)
    return ip_int & ((0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF), size, prefix


def expand_cidr(cidr: str) -> tuple[int, int]:
    """CIDR → (first_int, last_int) 闭区间；解析失败抛 ValueError。≤30 排除网络号
    与广播且**不截断**（/16 保留 65534 个），/31、/32 全保留。假设：前缀 0 直接
    抛错——覆盖整个 IPv4 空间，是手滑 0.0.0.0/0 的典型入口（scan 私有闸门先触发）。
    """
    net, size, prefix = _parse_cidr(cidr)
    if prefix == 0:
        raise ValueError("拒绝 /0 网段（覆盖整个 IPv4 空间）：%r" % (cidr,))
    return (net + 1, net + size - 2) if prefix <= 30 else (net, net + size - 1)


def is_private_host(ip: str) -> bool:
    """是否落在 10/8、172.16/12、192.168/16、127/8、169.254/16；非法输入 False。"""
    try:  # 不用 ipaddress.is_private：它把 100.64/10 等 CGNAT / 基准段也算私有
        addr = ipaddress.IPv4Address(str(ip).strip())
    except (ValueError, AttributeError):
        return False
    return any(addr in net for net in _PRIVATE_NETS)


def is_private_network(cidr: str) -> bool:
    """整个网段是否都私有（首尾双端）；非法 CIDR 返回 False。"""
    try:  # 双端而非只看网络号：10.0.0.0/7 这类横跨公私的网段必须被拒
        net, size, _ = _parse_cidr(cidr)
    except (ValueError, AttributeError):
        return False
    return is_private_host(int_to_ip(net)) and is_private_host(int_to_ip(net + size - 1))


def parse_port_range(spec: str) -> tuple[list[int], list[str]]:
    """解析 ``"7890,10808 1080-1085"`` → (ports, warnings)。分隔符 [,\\s]+；a-b
    展开为闭区间且 a>b 自动纠正为 b..a（不截断）；越界（<1 或 >65535）整段跳过
    并记 warning；ports 去重且保持首次出现顺序。
    """
    ports, warnings, seen = [], [], set()
    for token in (t for t in _SPLIT.split(str(spec or "")) if t):
        span = _RE_SPAN.match(token)
        if span is None and not _RE_PORT.match(token):
            warnings.append("忽略无效的端口标记：%s" % token)
            continue
        lo, hi = ((int(span.group(1)), int(span.group(2))) if span
                  else (int(token), int(token)))
        lo, hi = min(lo, hi), max(lo, hi)
        if lo < 1 or hi > 65535:
            warnings.append("端口超出范围 1-65535，已跳过：%s" % token)
            continue
        for port in range(lo, hi + 1):
            if port not in seen:
                seen.add(port)
                ports.append(port)
    return ports, warnings


def _notify(cb, done, total=1.0):
    """进度回调；UI 回调抛异常不得中断扫描。"""
    try:
        cb(done, total) if cb is not None else None
    except Exception:
        pass


def _run_pool(total, items, worker, *, max_workers, cancel, on_progress):
    """有界并发执行 worker(item)，收集非 None 结果；单任务异常不中断整批。items
    为惰性生成器（/16 × 6 端口 ≈ 39 万任务），按 max_workers × 4 分批提交。
    """
    results, done = [], 0
    workers = max(1, int(max_workers))
    if total <= 0 or (cancel is not None and cancel.is_set()):
        return results
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while done < total:
            batch = list(islice(items, workers * 4))
            if not batch or (cancel is not None and cancel.is_set()):
                break
            for fut in as_completed([pool.submit(worker, it) for it in batch]):
                done += 1
                try:
                    res = fut.result()
                except Exception:
                    res = None
                if res is not None:
                    results.append(res)
                _notify(on_progress, done, total)
    return results


def _local_ips() -> set:  # 本机 LAN IP；取不到则不排除任何主机
    try:
        return {socket.gethostbyname(socket.gethostname())}
    except OSError:
        return set()


_create_connection = socket.create_connection


def _probe_tcp(address, timeout):  # 单次 TCP 探测：连上返回 address，否则 None
    try:
        with _create_connection(address, timeout):  # with 保证连接必被关闭
            return address
    except OSError:
        return None


def tcp_probe(hosts, ports, *, timeout=1.0, max_workers=64, cancel=None,
              on_progress=None, exclude_self=True):
    """阶段一：hosts × ports 笛卡尔积并发探测，返回 [(ip, port)]（顺序不保证）。
    默认排除本机 LAN IP（原版规格要求）；本机自跑 Clash 想被扫到时传
    exclude_self=False。网络号与广播地址已由 expand_cidr 排除。
    """
    blocked = _local_ips() if exclude_self else set()
    targets, port_list = [h for h in hosts if h not in blocked], list(ports)
    if not targets or not port_list:
        return []
    return _run_pool(
        len(targets) * len(port_list),
        ((h, p) for h in targets for p in port_list),
        lambda item: _probe_tcp(item, timeout),
        max_workers=max_workers, cancel=cancel, on_progress=on_progress)


def _verify_one(ip, port, target, https_target, connect_timeout, read_timeout):
    """单个端点的真伪判定；失败返回 None，由调用方丢弃（不中断整批）。"""
    proxy = "http://%s:%s" % (ip, port)
    proxies, timeout = {"http": proxy, "https": proxy}, (connect_timeout, read_timeout)
    try:
        resp = requests.get(target, proxies=proxies, allow_redirects=False, timeout=timeout)
        if getattr(resp, "status_code", 0) != EXPECTED_STATUS:
            return None
        elapsed = getattr(getattr(resp, "elapsed", None), "total_seconds", None)
        latency = int(round(elapsed() * 1000)) if callable(elapsed) else 0
    except Exception:
        return None
    # HTTPS 侧只判定 CONNECT 隧道能力、不计时：隧道建连语义与 http 明文请求不同，
    # 混算会污染排序。代理层不抛异常即视为隧道可用。
    try:
        requests.get(https_target, proxies=proxies, allow_redirects=False, timeout=timeout)
        kind = "Mixed"
    except Exception:
        kind = "仅HTTP"
    return ProxyCandidate(ip=ip, port=port, latency_ms=latency, kind=kind)


def _normalize_endpoints(candidates):
    """统一 (ip, port) 元组与 ProxyCandidate 两种入参（dataclass 不可下标）。"""
    return [(c.ip, c.port) if isinstance(c, ProxyCandidate) else (c[0], c[1])
            for c in (candidates or [])]


def verify_proxy(candidates, *, max_workers=16, target=DEFAULT_TARGET,
                 connect_timeout=5.0, read_timeout=12.0, cancel=None,
                 on_progress=None, https_target=DEFAULT_HTTPS_TARGET):
    """阶段二：并发验证端点，按 latency_ms 升序返回真代理。

    candidates 接受 ``(ip, port)`` 元组或 ProxyCandidate 两种形态。
    """
    endpoints = _normalize_endpoints(candidates)
    if not endpoints:
        return []
    found = _run_pool(
        len(endpoints), iter(endpoints),
        lambda ep: _verify_one(*ep, target, https_target, connect_timeout, read_timeout),
        max_workers=max_workers, cancel=cancel, on_progress=on_progress)
    found.sort(key=lambda c: c.latency_ms)
    return found


def rate_latency(ms: int) -> str:  # 评级三档（与原版一致）
    return "✅ 优秀" if ms < 100 else ("👍 良好" if ms < 300 else "⚠️ 较慢")


def _stage(on_progress, lo, hi):
    """把子阶段 (done, total) 线性映射到总进度区间 [lo, hi]。"""
    if on_progress is None:
        return None
    return lambda d, t: t > 0 and _notify(on_progress, lo + (hi - lo) * (d / t))


def scan(subnet=DEFAULT_SUBNET, port_spec="", *, timeout=1.0, max_workers=64,
         verify_max_workers=16, cancel=None, on_progress=None, exclude_self=True):
    """三段式编排：私有性 → 规模 → 端口校验 → TCP 探测 → 代理验证 → 按延迟排序。
    on_progress(done, total) 的 total 恒为 1.0、done ∈ [0,1]：阶段一映射到
    0→0.5，阶段二映射到 0.5→1.0。port_spec 为空时回落到 DEFAULT_PORTS。

    exclude_self 只透传给 tcp_probe（默认 True 保持既有契约）。用户常要找**本机**
    自跑的 Clash，UI 因此提供「包含本机」勾选并传 False。
    """
    if not is_private_network(subnet):
        raise ScanRejected("网段不在私有段内：%s" % (subnet,))
    try:
        first, last = expand_cidr(subnet)
    except ValueError as exc:
        raise ScanRejected("网段解析失败：%s（%s）" % (subnet, exc)) from exc
    count = last - first + 1
    if count > MAX_HOSTS:
        raise ScanRejected("网段过大：%d 个地址，上限 %d" % (count, MAX_HOSTS))
    ports, warnings = parse_port_range(port_spec or " ".join(str(p) for p in DEFAULT_PORTS))
    if not ports:
        raise ScanRejected("未解析到任何有效端口：%s" % ("；".join(warnings) or port_spec))
    _notify(on_progress, 0.0)
    open_ends = tcp_probe(
        (int_to_ip(v) for v in range(first, last + 1)), ports, timeout=timeout,
        max_workers=max_workers, cancel=cancel, exclude_self=exclude_self,
        on_progress=_stage(on_progress, 0.0, 0.5))
    found = verify_proxy(open_ends, max_workers=verify_max_workers, cancel=cancel,
                         on_progress=_stage(on_progress, 0.5, 1.0))
    _notify(on_progress, 1.0)
    return found
