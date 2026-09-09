"""页面选择器对话框：交互方法续篇（open-class 延续 dialog_core）。"""
from core.qt_bootstrap import import_qt
from ..rss_store import scrape_html as _backend_scrape_html, _parse_selector
from .dialog_core import PageSelectorDialog
from .picker_js import _PICKER_JS

_, QtCore, QtGui, QtWidgets = import_qt()

class PageSelectorDialog(PageSelectorDialog):  # type: ignore[reportGeneralTypeIssues]

    # ── 控制 ──────────────────────────────────────────
    def _load(self):
        self._url = self.in_url.text().strip()
        if self._url:
            if not self._url.startswith(("http://", "https://")):
                self._url = "http://" + self._url
                self.in_url.setText(self._url)
            self.web.load(QtCore.QUrl(self._url))

    def _on_loaded(self, ok):
        self.web.page().runJavaScript(_PICKER_JS)

    def _run(self, js, callback=None):
        self.web.page().runJavaScript(js, callback or (lambda _r: None))

    def _js_quote(self, s):
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _start_keyword(self):
        kw = self.kw_input.text().strip()
        if not kw:
            return
        self._run(f'window.__yzTogglePickMode("keyword", {self._js_quote(kw)});')
        self._set_mode_text("点选模式：蓝色虚线为含关键词的块，点击其一即可锁定该类元素。")
        self._start_polling()

    def _pick(self, mode, kw=None):
        self._stop_polling()
        for b in (self.btn_single, self.btn_list, self.btn_multi):
            b.setChecked(False)
        self.btn_multi_gen.setVisible(False)
        self.lb_multi_count.setText("")
        self._run(f'window.__yzTogglePickMode("{mode}", {self._js_quote(kw or "")});')
        if mode == "multi":
            self.btn_multi.setChecked(True)
            self.btn_multi_gen.setVisible(True)
            self.mode_label.setText("多选模式：逐个点击要监控的元素（绿色表示已选，再点取消）。选好后点「生成多选」自动分析公共部分。")
        else:
            tips = {
                "single": "单元素模式：点击一个元素，作为单独一条监控。",
                "list": "列表容器模式：点击容器，给其子元素生成选择器，每个子元素成为一条 RSS。",
            }
            self._set_mode_text(tips.get(mode, ""))
        self._start_polling()

    def _set_mode_text(self, text):
        self.mode_label.setText(text)

    def _apply_manual_selector(self):
        sel = self.selector_input.text().strip()
        if not sel:
            return
        self._options["selector"] = sel
        self._last_selector = sel
        self._read_count(sel)

    def _finalize_multi(self):
        self._run("window.__yzFinalizeMulti();", self._read_result)

    def _start_polling(self):
        if self._poll is not None:
            return

        def poll():
            self._run(
                "var r = window.__yzResult; window.__yzResult = null; "
                "JSON.stringify({done: !!window.__yzDone, mode: r?r.mode:'', "
                "selector: r?r.selector:'', text: r?r.text:'', "
                "multiCount: window.__yzMultiCount?window.__yzMultiCount():0});",
                self._read_result,
            )
        self._poll = QtCore.QTimer()
        self._poll.timeout.connect(poll)
        self._poll.start(150)

    def _read_result(self, sres):
        try:
            import json
            r = json.loads(str(sres))
        except Exception:
            r = None
        if not r:
            return
        if self._in_multi or self.btn_multi.isChecked():
            self.lb_multi_count.setText(f"已选 {r.get('multiCount', 0)} 个")
        if r.get("done"):
            sel = (r.get("selector") or "").strip()
            mode = r.get("mode") or "single"
            if sel:
                self._last_selector = sel
                self.selector_input.setText(sel)
                self._options["mode"] = mode
                self._options["selector"] = sel
                self._sync_mode_buttons(mode)
                self.mode_label.setText(f"已锁定（{ '列表' if mode=='list' else '单元素' }）：{sel}")
                self._stop_polling()

    def _sync_mode_buttons(self, mode):
        self.btn_single.setChecked(mode == "single")
        self.btn_list.setChecked(mode == "list")
        self.btn_multi.setChecked(False)
        self.btn_multi_gen.setVisible(False)

    def _stop_polling(self):
        if self._poll is not None:
            self._poll.stop()
            self._poll = None
        self._run("window.__yzStop();")

    def _read_count(self, sel):
        try:
            html = self._fetch_html()
            from ..rss_store import _build_dom, find_elements
            dom = _build_dom(html)
            count = len(find_elements(dom, sel))
            try:
                _parse_selector(sel)
                parse_ok = True
            except Exception:
                parse_ok = False
            hint = "" if parse_ok else "（该选择器可能超出引擎支持范围）"
            self.lb_count.setText(f"匹配 {count} 个{hint}")
        except Exception as e:
            self.lb_count.setText(f"匹配失败: {e}")

    # ── 测试与预览（用后端纯 Python 引擎）────────────
    def _current_options(self):
        sel = self.selector_input.text().strip()
        mode = self._options.get("mode", "single")
        if self.btn_list.isChecked():
            mode = "list"
        if self.btn_single.isChecked():
            mode = "single"
        if self.btn_multi.isChecked() and sel:
            mode = "list"
        return {"mode": mode, "selector": sel}

    def _fetch_html(self):
        import requests
        from ..rss_store import _detect_encoding
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YZplan/1.0"}
        resp = requests.get(self.in_url.text().strip(), timeout=15, headers=headers)
        resp.raise_for_status()
        enc = _detect_encoding(resp.content)
        try:
            return resp.content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            return resp.content.decode("utf-8", errors="replace")

    def _test_match(self):
        sel = self.selector_input.text().strip()
        if not sel:
            return
        self._read_count(sel)

    def _preview_extract(self):
        opts = self._current_options()
        if not opts["selector"]:
            return
        try:
            html = self._fetch_html()
            entries = _backend_scrape_html(html, opts, self.in_url.text().strip())
            lines = [f"模式: {'列表' if opts['mode']=='list' else '单元素'} | 选择器: {opts['selector']}", ""]
            if not entries:
                lines.append("未提取到任何条目")
            for i, e in enumerate(entries[:20], 1):
                lines.append(f"{i}. {e['title']}  {e['link']}")
            if len(entries) > 20:
                lines.append(f"... 共 {len(entries)} 条")
            QtWidgets.QMessageBox.information(self, "抓取预览", "\n".join(lines))
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "抓取预览", f"失败: {e}")

    # ── 完成 ──────────────────────────────────────────
    def _finish(self):
        self._stop_polling()
        opts = self._current_options()
        self._options = dict(self._options)
        if opts["selector"]:
            self._options.update(opts)
        self.accept()

    def options(self):
        return self._options
