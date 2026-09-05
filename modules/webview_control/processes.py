"""webview_control - process scan helpers."""

def scan_processes():
    import psutil
    procs = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "memory_info", "num_threads"]):
        try:
            info = proc.info
            if info["name"] and "msedgewebview2" in info["name"].lower():
                connections = []
                try:
                    for conn in proc.connections(kind="inet"):
                        laddr = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else ""
                        raddr = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else ""
                        connections.append({
                            "laddr": laddr, "raddr": raddr,
                            "status": conn.status, "type": "TCP",
                        })
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                try:
                    for conn in proc.net_connections():
                        pass
                except Exception:
                    pass
                mem = info.get("memory_info")
                procs.append({
                    "pid": info["pid"],
                    "exe": info.get("exe") or "",
                    "cmdline": " ".join(info.get("cmdline") or []),
                    "rss_mb": round(mem.rss / 1024 / 1024, 1) if mem else 0,
                    "threads": info.get("num_threads", 0),
                    "connections": connections,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs
