"""scanner.py 单元测试（纯 Python 数据层：无 Qt、无真实网络）。

纪律（AGENTS.md 测试规范）：
- 模块顶层零副作用：不建 QApplication、不读文件、不写环境变量；
- 绝不真连任何地址或端口：TCP 走 ``scanner._create_connection`` 替身，
  HTTP 走 ``monkeypatch.setattr(scanner, "requests", 替身)`` 替身。
"""
import ipaddress
import threading
import types

import pytest

from modules.proxy_ctrl import scanner
from modules.proxy_ctrl.scanner import (
    DEFAULT_PORTS,
    DEFAULT_SUBNET,
    MAX_HOSTS,
    ProxyCandidate,
    ScanRejected,
    expand_cidr,
    int_to_ip,
    is_private_host,
    is_private_network,
    parse_port_range,
    ProxyCandidate,
    rate_latency,
    scan,
    tcp_probe,
    verify_proxy,
)


def _ipint(ip):
    """测试侧的 "192.168.2.1" → int 助手（scanner 只导出 int_to_ip 单向）。"""
    return int(ipaddress.IPv4Address(ip))


# --------------------------------------------------------------- 替身

class _FakeSocket:
    """socket 替身：必须支持上下文管理器协议（scanner._probe_tcp 用 `with`）。"""

    def __init__(self):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def close(self):
        self.closed = True


class _FakeResponse:
    """最小 requests.Response 替身：只需 status_code 与 elapsed。"""

    def __init__(self, status_code, elapsed_ms=50):
        self.status_code = status_code
        self.elapsed = types.SimpleNamespace(
            total_seconds=(lambda ms=elapsed_ms: ms / 1000.0))


def _install_requests(monkeypatch, table, calls=None):
    """用替身替换 scanner.requests。

    table: {url: (status_code, elapsed_ms) | Exception}；未登记的 url 直接断言失败。
    """
    calls = [] if calls is None else calls

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        if url not in table:
            raise AssertionError("未预期的请求目标：%s" % url)
        item = table[url]
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(*item)

    monkeypatch.setattr(scanner, "requests", types.SimpleNamespace(get=_get))
    return calls


def _install_connector(monkeypatch, open_ports, local_ips=frozenset()):
    """假 socket：open_ports 里的端口连得上，其余抛 OSError。返回调用记录。"""
    seen = []

    def _conn(address, timeout):
        seen.append((address, timeout))
        if address[1] in open_ports:
            return _FakeSocket()
        raise OSError("connection refused: %s" % (address,))

    monkeypatch.setattr(scanner, "_create_connection", _conn)
    monkeypatch.setattr(scanner, "_local_ips", lambda: set(local_ips))
    return seen


HTTP_TARGET = scanner.DEFAULT_TARGET
HTTPS_TARGET = scanner.DEFAULT_HTTPS_TARGET


# ------------------------------------------------------- parse_port_range

def test_parse_port_range_single():
    assert parse_port_range("7890") == ([7890], [])


def test_parse_port_range_comma_separated():
    assert parse_port_range("7890,10808") == ([7890, 10808], [])


def test_parse_port_range_space_separated():
    assert parse_port_range("7890 10808") == ([7890, 10808], [])


def test_parse_port_range_mixed_separators():
    assert parse_port_range("7890, 10808 3128") == ([7890, 10808, 3128], [])


def test_parse_port_range_expands_closed_interval():
    assert parse_port_range("1-5")[0] == [1, 2, 3, 4, 5]


def test_parse_port_range_corrects_reversed_interval():
    """a > b 自动纠正为 b..a，不截断（原版容错语义）。"""
    assert parse_port_range("5-1")[0] == [1, 2, 3, 4, 5]


def test_parse_port_range_invalid_tokens_warned():
    ports, warnings = parse_port_range("7890,bad,abc")
    assert ports == [7890]
    assert len(warnings) == 2
    assert all("bad" in w or "abc" in w for w in warnings)


@pytest.mark.parametrize("spec", ["0", "70000", "65536"])
def test_parse_port_range_out_of_range_single_skipped(spec):
    ports, warnings = parse_port_range(spec)
    assert ports == []
    assert len(warnings) == 1
    assert spec in warnings[0]


def test_parse_port_range_out_of_range_segment_skipped():
    ports, warnings = parse_port_range("1-70000")
    assert ports == []
    assert len(warnings) == 1


def test_parse_port_range_dedups_preserving_first_order():
    ports, warnings = parse_port_range("7890,10808,7890,10808")
    assert ports == [7890, 10808]
    assert warnings == []


def test_parse_port_range_empty_spec():
    assert parse_port_range("") == ([], [])


def test_parse_port_range_non_numeric_range_skipped():
    ports, warnings = parse_port_range("a-b")
    assert ports == []
    assert len(warnings) == 1


def test_parse_port_range_all_default_ports_parse():
    assert parse_port_range(" ".join(str(p) for p in DEFAULT_PORTS))[0] == list(DEFAULT_PORTS)


# ----------------------------------------------------------- expand_cidr

def test_expand_cidr_slash24_excludes_network_and_broadcast():
    first, last = expand_cidr("192.168.2.0/24")
    assert int_to_ip(first) == "192.168.2.1"
    assert int_to_ip(last) == "192.168.2.254"
    assert last - first + 1 == 254


def test_expand_cidr_slash30_keeps_two_hosts():
    first, last = expand_cidr("10.0.0.0/30")
    assert (int_to_ip(first), int_to_ip(last)) == ("10.0.0.1", "10.0.0.2")
    assert last - first + 1 == 2


def test_expand_cidr_slash16_is_not_truncated():
    """不截断：/16 保留 65534 个地址（原版语义）。"""
    first, last = expand_cidr("10.0.0.0/16")
    assert last - first + 1 == 65534
    assert int_to_ip(first) == "10.0.0.1"
    assert int_to_ip(last) == "10.0.255.254"


def test_expand_cidr_slash31_keeps_both_addresses():
    first, last = expand_cidr("192.168.2.5/31")
    assert (int_to_ip(first), int_to_ip(last)) == ("192.168.2.4", "192.168.2.5")


def test_expand_cidr_slash32_keeps_single_address():
    first, last = expand_cidr("192.168.2.5/32")
    assert first == last == _ipint("192.168.2.5")


def test_expand_cidr_default_prefix_is_24():
    assert expand_cidr("192.168.2.5") == expand_cidr("192.168.2.0/24")


def test_expand_cidr_prefix_above_32_clamped():
    first, last = expand_cidr("192.168.2.0/33")
    assert first == last == _ipint("192.168.2.0")


def test_expand_cidr_rejects_prefix_zero():
    """安全闸门：/0 覆盖整个 IPv4 空间，直接报错而不是物化 42 亿地址。"""
    with pytest.raises(ValueError):
        expand_cidr("0.0.0.0/0")


def test_expand_cidr_invalid_raises():
    with pytest.raises(ValueError):
        expand_cidr("abc")
    with pytest.raises(ValueError):
        expand_cidr("192.168.2.256/24")
    with pytest.raises(ValueError):
        expand_cidr("")


def test_expand_cidr_uses_unsigned_32bit_int():
    """/8 段不因浮点溢出：10.255.255.254 必须能算出。"""
    first, last = expand_cidr("10.0.0.0/8")
    assert int_to_ip(first) == "10.0.0.1"
    assert int_to_ip(last) == "10.255.255.254"


# ------------------------------------------------------------ 私有段闸门

@pytest.mark.parametrize("ip, expected", [
    ("192.168.2.1", True),
    ("10.0.0.1", True),
    ("172.16.0.1", True),
    ("172.32.0.1", False),
    ("127.0.0.1", True),
    ("169.254.1.1", True),
    ("8.8.8.8", False),
    ("1.1.1.1", False),
    ("172.15.0.1", False),
    ("11.0.0.1", False),
    ("192.169.0.1", False),
    ("garbage", False),
])
def test_is_private_host(ip, expected):
    assert is_private_host(ip) is expected


def test_is_private_network():
    assert is_private_network("192.168.2.0/24") is True
    assert is_private_network("10.0.0.0/8") is True
    assert is_private_network("8.8.8.0/24") is False
    assert is_private_network("0.0.0.0/0") is False
    assert is_private_network("garbage") is False


def test_is_private_network_rejects_public_straddling_range():
    """10.0.0.0/7 横跨公私，首尾双端判定必须拒绝。"""
    assert is_private_network("10.0.0.0/7") is False


# -------------------------------------------------------------- tcp_probe

def test_tcp_probe_returns_only_open_ports(monkeypatch):
    seen = _install_connector(monkeypatch, open_ports={7890})
    hosts = ["192.168.2.1", "192.168.2.2", "192.168.2.3"]
    result = tcp_probe(hosts, [7890, 8080], timeout=0.3)
    assert sorted(result) == [("192.168.2.1", 7890), ("192.168.2.2", 7890),
                              ("192.168.2.3", 7890)]
    assert len(seen) == 6  # 笛卡尔积全探


def test_tcp_probe_passes_timeout_through(monkeypatch):
    seen = _install_connector(monkeypatch, open_ports=set())
    tcp_probe(["192.168.2.1"], [7890], timeout=0.25)
    assert seen == [(("192.168.2.1", 7890), 0.25)]


def test_tcp_probe_excludes_local_ip(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890}, local_ips={"192.168.2.5"})
    result = tcp_probe(["192.168.2.5", "192.168.2.6"], [7890])
    assert result == [("192.168.2.6", 7890)]


def test_tcp_probe_can_keep_local_ip(monkeypatch):
    """本机自跑 Clash 时 LAN IP 上的代理是用户真正要找的，可显式保留。"""
    _install_connector(monkeypatch, open_ports={7890}, local_ips={"192.168.2.5"})
    result = tcp_probe(["192.168.2.5"], [7890], exclude_self=False)
    assert result == [("192.168.2.5", 7890)]


def test_tcp_probe_precancelled_returns_empty(monkeypatch):
    seen = _install_connector(monkeypatch, open_ports={7890})
    cancel = threading.Event()
    cancel.set()
    assert tcp_probe(["192.168.2.1"], [7890], cancel=cancel) == []
    assert seen == []


def test_tcp_probe_reports_progress(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    seen_progress = []
    tcp_probe(["192.168.2.1", "192.168.2.2"], [7890, 8080],
              on_progress=lambda done, total: seen_progress.append((done, total)))
    assert seen_progress
    assert seen_progress[-1] == (4, 4)
    assert [d for d, _ in seen_progress] == sorted(d for d, _ in seen_progress)


def test_tcp_probe_empty_inputs(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    assert tcp_probe([], [7890]) == []
    assert tcp_probe(["192.168.2.1"], []) == []


# ----------------------------------------------------------- verify_proxy

def test_verify_proxy_only_204_is_a_real_proxy(monkeypatch):
    """核心防误报规则：200/301/404/403 一律拒绝（Web 服务器会返回它们）。"""
    for bad_status in (200, 301, 404, 403, 500):
        _install_requests(monkeypatch, {HTTP_TARGET: (bad_status, 20)})
        assert verify_proxy([("192.168.2.9", 7890)]) == []


def test_verify_proxy_accepts_204(monkeypatch):
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 42)})
    found = verify_proxy([("192.168.2.9", 7890)])
    assert len(found) == 1
    c = found[0]
    assert (c.ip, c.port, c.latency_ms) == ("192.168.2.9", 7890, 42)
    assert c.kind == "仅HTTP"
    assert c.scheme == "http"


def test_verify_proxy_kind_mixed_when_https_tunnel_works(monkeypatch):
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 30), HTTPS_TARGET: (204, 80)})
    assert verify_proxy([("192.168.2.9", 7890)])[0].kind == "Mixed"


def test_verify_proxy_kind_http_only_when_https_raises(monkeypatch):
    """不支持 CONNECT 的代理，requests 抛 ProxyError → 仅HTTP。"""
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 30),
                                    HTTPS_TARGET: OSError("proxy CONNECT refused")})
    assert verify_proxy([("192.168.2.9", 7890)])[0].kind == "仅HTTP"


def test_verify_proxy_kind_http_only_when_https_fails_fast(monkeypatch):
    """HTTPS 侧连接失败也算仅HTTP，不影响 http 侧已通过的判定。"""
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 30),
                                    HTTPS_TARGET: OSError("read timeout")})
    assert len(verify_proxy([("192.168.2.9", 7890)])) == 1


def test_verify_proxy_drops_exceptions_without_aborting_batch(monkeypatch):
    def _get(url, **kwargs):
        if url != HTTP_TARGET:
            return _FakeResponse(204, 10)  # HTTPS 能力探测
        ip = kwargs["proxies"]["http"]
        if "192.168.2.1" in ip:
            raise OSError("proxy died")
        if "192.168.2.2" in ip:
            raise RuntimeError("unexpected adapter failure")
        return _FakeResponse(204, 55)

    monkeypatch.setattr(scanner, "requests", types.SimpleNamespace(get=_get))
    found = verify_proxy([("192.168.2.1", 7890), ("192.168.2.2", 7890),
                          ("192.168.2.3", 7890)])
    assert [(c.ip, c.port) for c in found] == [("192.168.2.3", 7890)]


def test_verify_proxy_sorted_by_latency_ascending(monkeypatch):
    latencies = {"192.168.2.1": 300, "192.168.2.2": 15, "192.168.2.3": 120}

    def _get(url, **kwargs):
        if url == HTTPS_TARGET:
            return _FakeResponse(204, 5)
        host = kwargs["proxies"]["http"][len("http://"):].rsplit(":", 1)[0]
        return _FakeResponse(204, latencies[host])

    monkeypatch.setattr(scanner, "requests", types.SimpleNamespace(get=_get))
    found = verify_proxy([("192.168.2.1", 7890), ("192.168.2.2", 10808),
                          ("192.168.2.3", 3128)])
    assert [c.latency_ms for c in found] == [15, 120, 300]


def test_verify_proxy_uses_expected_requests_kwargs(monkeypatch):
    calls = _install_requests(monkeypatch, {HTTP_TARGET: (204, 20), HTTPS_TARGET: (204, 25)})
    verify_proxy([("192.168.2.9", 7890)], connect_timeout=5.0, read_timeout=12.0)
    http_call = calls[0]
    assert http_call[0] == HTTP_TARGET
    assert http_call[1]["proxies"] == {"http": "http://192.168.2.9:7890",
                                       "https": "http://192.168.2.9:7890"}
    assert http_call[1]["allow_redirects"] is False
    assert http_call[1]["timeout"] == (5.0, 12.0)
    assert calls[1][0] == HTTPS_TARGET


def test_verify_proxy_precancelled_returns_empty(monkeypatch):
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 20), HTTPS_TARGET: (204, 25)})
    cancel = threading.Event()
    cancel.set()
    assert verify_proxy([("192.168.2.9", 7890)], cancel=cancel) == []


def test_verify_proxy_reports_progress(monkeypatch):
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 20), HTTPS_TARGET: (204, 25)})
    progress = []
    verify_proxy([("192.168.2.1", 7890), ("192.168.2.2", 7890)],
                 on_progress=lambda d, t: progress.append((d, t)))
    assert progress[-1] == (2, 2)


def test_verify_proxy_empty_candidates(monkeypatch):
    _install_requests(monkeypatch, {})
    assert verify_proxy([]) == []


# ----------------------------------------------------------- rate_latency

def test_rate_latency_boundaries():
    assert rate_latency(0) == "✅ 优秀"
    assert rate_latency(99) == "✅ 优秀"
    assert rate_latency(100) == "👍 良好"
    assert rate_latency(299) == "👍 良好"
    assert rate_latency(300) == "⚠️ 较慢"
    assert rate_latency(9999) == "⚠️ 较慢"


# ------------------------------------------------------------------ scan

def test_scan_rejects_public_subnet(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    with pytest.raises(ScanRejected) as exc:
        scan("8.8.8.0/24", "7890")
    assert "8.8.8.0/24" in str(exc.value)


def test_scan_rejects_whole_ipv4_space(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    with pytest.raises(ScanRejected):
        scan("0.0.0.0/0", "7890")


def test_scan_rejects_oversized_private_subnet(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    with pytest.raises(ScanRejected) as exc:
        scan("10.0.0.0/8", "7890")
    assert "16777214" in str(exc.value)
    assert str(MAX_HOSTS) in str(exc.value)


def test_scan_rejects_malformed_subnet(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    with pytest.raises(ScanRejected):
        scan("not-a-subnet", "7890")


def test_scan_rejects_all_invalid_ports(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    with pytest.raises(ScanRejected) as exc:
        scan("192.168.2.0/29", "bad,also-bad")
    assert "bad" in str(exc.value)


def test_scan_end_to_end_sorted_and_progressed(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    proxies = {"192.168.2.2": 120, "192.168.2.5": 40}

    def _get(url, **kwargs):
        if url == HTTPS_TARGET:
            return _FakeResponse(204, 9)  # 隧道可用 → Mixed
        host = kwargs["proxies"]["http"][len("http://"):].rsplit(":", 1)[0]
        if host not in proxies:
            raise OSError("不是代理")
        return _FakeResponse(204, proxies[host])

    monkeypatch.setattr(scanner, "requests", types.SimpleNamespace(get=_get))
    progress = []
    found = scan("192.168.2.0/29", "7890,8080",
                 on_progress=lambda d, t: progress.append((d, t)))
    # /29 → 6 台主机 × 2 端口；只有 7890 开放，其中两台转发出 204，按延迟升序
    assert [(c.ip, c.port, c.latency_ms, c.kind) for c in found] == [
        ("192.168.2.5", 7890, 40, "Mixed"),
        ("192.168.2.2", 7890, 120, "Mixed"),
    ]
    assert progress[-1] == (1.0, 1.0)
    assert all(0.0 <= d <= 1.0 for d, _ in progress)


def test_scan_progress_stays_within_half_split(monkeypatch):
    """阶段一映射到 0→0.5，阶段二映射到 0.5→1.0。"""
    _install_connector(monkeypatch, open_ports={7890})
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 20), HTTPS_TARGET: (204, 25)})
    progress = []
    scan("192.168.2.0/29", "7890", on_progress=lambda d, t: progress.append((d, t)))
    assert progress[0] == (0.0, 1.0)
    assert max(progress, key=lambda p: p[0])[0] == 1.0
    assert all(t == 1.0 for _, t in progress)


def test_scan_precancelled_returns_empty(monkeypatch):
    _install_connector(monkeypatch, open_ports={7890})
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 20)})
    cancel = threading.Event()
    cancel.set()
    assert scan("192.168.2.0/29", "7890", cancel=cancel) == []


def test_scan_defaults_are_self_consistent():
    assert DEFAULT_SUBNET == "192.168.2.0/24"
    assert is_private_network(DEFAULT_SUBNET) is True
    assert expand_cidr(DEFAULT_SUBNET)[1] - expand_cidr(DEFAULT_SUBNET)[0] + 1 < MAX_HOSTS


def test_verify_proxy_accepts_proxy_candidate_objects(monkeypatch):
    """入参也接受 ProxyCandidate（dataclass 不可下标，需显式归一化）。"""
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 20), HTTPS_TARGET: (204, 25)})
    seed = ProxyCandidate(ip="192.168.2.9", port=7890, latency_ms=0, kind="")
    found = verify_proxy([seed])
    assert len(found) == 1
    assert (found[0].ip, found[0].port) == ("192.168.2.9", 7890)


def test_verify_proxy_mixes_tuple_and_candidate_forms(monkeypatch):
    _install_requests(monkeypatch, {HTTP_TARGET: (204, 20), HTTPS_TARGET: (204, 25)})
    seed = ProxyCandidate(ip="192.168.2.8", port=7890, latency_ms=0, kind="")
    found = verify_proxy([seed, ("192.168.2.9", 10808)])
    assert sorted((c.ip, c.port) for c in found) == [
        ("192.168.2.8", 7890), ("192.168.2.9", 10808)]


def test_verify_proxy_empty_input(monkeypatch):
    assert verify_proxy([]) == []
    assert verify_proxy(None) == []
