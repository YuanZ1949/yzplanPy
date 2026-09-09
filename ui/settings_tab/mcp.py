"""SettingsTab MCP 服务器卡片：开关、启动命令、工具数、测试连接（跨线程桥接）。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, PushButton, StrongBodyLabel, SwitchButton
_, QtCore, QtGui, QtWidgets = import_qt()
from .rows import SettingsTab

class SettingsTab(SettingsTab):  # type: ignore[reportGeneralTypeIssues]

    def _build_mcp_section(self, parent):
        """MCP 服务器卡片：开关、启动命令、工具数量、测试连接。"""
        import json

        # 开关：是否在本应用内启动 Http MCP 服务（stdio 作为独立进程命令始终可用）
        mcp_sw_row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(mcp_sw_row)
        rl.setContentsMargins(0, 6, 0, 0)
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(StrongBodyLabel("启用 MCP HTTP 服务"))
        txt.addWidget(BodyLabel("在 127.0.0.1:8765 提供本地 MCP 接口，供外部客户端调用"))
        rl.addLayout(txt, 1)
        self.sw_mcp_http = SwitchButton()
        self.sw_mcp_http.setOnText("开")
        self.sw_mcp_http.setOffText("关")
        rl.addWidget(self.sw_mcp_http)
        parent.addWidget(mcp_sw_row)

        # 状态 / 工具数
        self.lb_mcp_status = BodyLabel("MCP 接口已注册，共 0 个工具")
        self.lb_mcp_status.setStyleSheet("color: #888;")
        parent.addWidget(self.lb_mcp_status)

        # stdio 与 http 启动命令
        def _cmd_row(label, command):
            row = QtWidgets.QWidget()
            rl2 = QtWidgets.QHBoxLayout(row)
            rl2.setContentsMargins(0, 2, 0, 2)
            rl2.addWidget(BodyLabel(label))
            edit = QtWidgets.QLineEdit(command)
            edit.setReadOnly(True)
            edit.setStyleSheet(
                "background: rgba(128,128,128,0.12); border: 1px solid rgba(128,128,128,0.2); "
                "border-radius: 6px; padding: 5px 10px; color: inherit;")
            edit.setCursorPosition(0)
            rl2.addWidget(edit, 1)
            btn = PushButton("复制")
            btn.clicked.connect(lambda _=False, e=edit: (
                QtWidgets.QApplication.clipboard().setText(e.text())))
            rl2.addWidget(btn)
            parent.addWidget(row)

        _cmd_row("stdio:", 'python mcp_server.py stdio')
        _cmd_row("HTTP:", 'python mcp_server.py http --port 8765')

        # 测试连接
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_test = PushButton("测试连接")
        btn_test.clicked.connect(self._test_mcp)
        btn_row.addWidget(btn_test)
        parent.addLayout(btn_row)

        # 初始化工具数量与开关状态
        try:
            import mcp_server
            self.lb_mcp_status.setText(f"MCP 接口已注册，共 {len(mcp_server.TOOLS)} 个工具")
        except Exception:
            self.lb_mcp_status.setText("MCP 模块未加载")
        enabled = self.context.config.get("mcp.enabled", False)
        self.sw_mcp_http.setChecked(bool(enabled))
        self.sw_mcp_http.checkedChanged.connect(self._on_mcp_http_toggled)

    def _on_mcp_http_toggled(self, on):
        """保存配置并在应用内启动/停止 MCP HTTP 服务线程。"""
        import threading
        self.context.config.set("mcp.enabled", bool(on))
        state = getattr(self, "_mcp_http_state", None)
        server = state.get("server") if state else None
        if on:
            if server is not None:
                return
            try:
                import mcp_server
                from wsgiref.simple_server import make_server
                host, port = "127.0.0.1", 8765
                httpd = make_server(host, port,
                                    lambda e, s: mcp_server._http_handler(e, s, {}))  # type: ignore[reportArgumentType]

                def serve():
                    httpd.serve_forever()

                t = threading.Thread(target=serve, daemon=True)
                t.start()
                self._mcp_http_state = {"alive": True, "server": httpd}
            except Exception:
                self._mcp_http_state = None
        else:
            if server is not None:
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
            self._mcp_http_state = {"alive": False, "server": None}

    def _test_mcp(self):
        """后台线程只做轻量计算，结果经跨线程安全的 bridge 信号回到主线程再弹提示。

        禁止在后台线程直接创建/操作 Qt widget（Qt 非线程安全，会让主线程事件循环卡死）；
        也不能用 QTimer.singleShot（从非 GUI 线程调用时 0ms 定时器不会投递到主线程）。
        """
        import threading

        def _run():
            try:
                import mcp_server
                result = mcp_server.handle_message({
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "todo_stats", "arguments": {}},
                })
                ok = result and result.get("result", {}).get("isError") is False
                msg = ("MCP 工作正常" if ok else "MCP 调用返回异常") + \
                      f": {len(mcp_server.TOOLS)} 个工具"
            except Exception as e:  # noqa: BLE001
                ok, msg = False, str(e)
            # 跨线程投递到主线程（QueuedConnection）；_on_mcp_result 只在主线程操作 GUI
            self._mcp_bridge.done.emit(ok, msg)

        threading.Thread(target=_run, daemon=True).start()

    def _on_mcp_result(self, ok, msg):
        from qfluentwidgets import InfoBar, InfoBarPosition
        if ok:
            InfoBar.success("测试完成", msg, parent=self.widget,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000)
        else:
            InfoBar.error("MCP 测试失败", msg, parent=self.widget,
                          position=InfoBarPosition.TOP_RIGHT, duration=3000)
