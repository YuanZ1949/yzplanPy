"""webview_control - remote IP blocking and rule listing (MCP-facing)."""

def block_remote_ip(host_or_path):
    """按 remoteip 添加防火墙拦截规则（MCP webview_block 语义：per-IP 出站拦截）。"""
    import subprocess
    try:
        cmd = f'netsh advfirewall firewall add rule name="YZplan_Block_{host_or_path}" dir=out action=block remoteip="{host_or_path}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10,
                                creationflags=0x08000000)
        return {"success": "OK" in result.stdout, "output": result.stdout.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def unblock_rule(name):
    """删除指定的 WebView2 防火墙拦截规则（MCP webview_unblock 语义）。"""
    import subprocess
    try:
        cmd = f'netsh advfirewall firewall delete rule name="YZplan_Block_{name}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10,
                                creationflags=0x08000000)
        return {"success": "OK" in result.stdout, "output": result.stdout.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_yzplan_rules():
    """列举当前所有 YZplan_Block_* 防火墙规则（MCP webview_rules 语义）。"""
    import subprocess
    try:
        result = subprocess.run(
            'netsh advfirewall firewall show rule name=all dir=out | findstr /I "YZplan_Block_"',
            shell=True, capture_output=True, text=True, timeout=10,
            creationflags=0x08000000)
        rules = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        return {"rules": rules, "count": len(rules)}
    except Exception as e:
        return {"rules": [], "count": 0, "error": str(e)}
