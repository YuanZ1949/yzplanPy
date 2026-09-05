"""页面选择器：用 QtWebEngine 打开网页，通过鼠标点选/多选/关键词/手动输入 CSS 选择器，
为「页面监控 RSS 源」锁定目标元素并生成可被 rss_store 引擎解析的选择器配置。

仅供交互使用；实际抓取由 rss_store.scrape_html / scrape_page 完成（纯 Python）。
"""
import logging
import sys

from core.qt_bootstrap import import_qt
from .rss_store import scrape_html as _backend_scrape_html, _parse_selector

logger = logging.getLogger("page_selector")

_, QtCore, QtGui, QtWidgets = import_qt()

def _webengine_view():
    """惰性导入 QWebEngineView：仅在真正打开选择器时才加载 WebEngine，
    避免任何 import 路径（含误 import 本模块）在启动期拉起 Chromium 线程池。"""
    mod = sys.modules.get("PySide6.QtWebEngineWidgets")
    if mod is not None:
        return getattr(mod, "QWebEngineView", None)
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception as _we:  # pragma: no cover
        logger.warning("QtWebEngine 不可用，页面选择器将不可用: %s", _we)
        return None
    return QWebEngineView

_PICKER_JS = r"""
(function(){
  if (window.__yzPickerInstalled) return;
  window.__yzPickerInstalled = true;
  window.__yzMode = null;          // 'single' | 'list' | 'multi' | 'keyword'
  window.__yzResult = null;
  window.__yzHover = null;
  window.__yzMulti = [];

  function cssEscape(s){ return s.replace(/[^0-9a-zA-Z_-]/g,'\\$&'); }

  function basicSelector(el){
    var tag = el.tagName.toLowerCase();
    var cls = Array.prototype.filter.call(el.classList, function(c){
      return /^[\w-]+$/.test(c);
    });
    var s = tag;
    if (cls.length) s += '.' + cls.join('.');
    return s;
  }
  function sameTagClass(a, b){
    if (a.tagName !== b.tagName) return false;
    var aS = Array.from(a.classList).sort().join(','), bS = Array.from(b.classList).sort().join(',');
    return aS === bS;
  }
  function levelSelector(el){
    var id = el.id || '';
    if (id && /^[A-Za-z_][\w-]*$/.test(id)) return '#' + cssEscape(id);
    var sel = basicSelector(el);
    if (!el.parentElement) return sel;
    var sibs = Array.from(el.parentElement.children).filter(function(s){
      return s !== el && sameTagClass(s, el);
    });
    if (sibs.length > 0){
      var sameTag = Array.from(el.parentElement.children).filter(function(s){
        return s.tagName === el.tagName;
      });
      var idx = sameTag.indexOf(el) + 1;
      sel += ':nth-of-type(' + idx + ')';
    }
    return sel;
  }
  function selectorFor(el){
    var parts = [];
    var node = el;
    while (node && node.nodeType === 1 && node !== document.body && node !== document.documentElement){
      var lv = levelSelector(node);
      var usedId = lv.charAt(0) === '#';
      parts.unshift(lv);
      if (usedId) break;
      node = node.parentElement;
    }
    return parts.join(' > ').toLowerCase();
  }
  // 列表容器：直接子元素的公共选择器
  function childrenSelector(el){
    var kids = Array.prototype.filter.call(el.children, function(c){ return c.nodeType === 1; });
    if (!kids.length) return selectorFor(el) + ' > *';
    var tags = new Set(), commonClasses = null;
    kids.forEach(function(k){
      tags.add(k.tagName.toLowerCase());
      var cs = Array.from(k.classList);
      commonClasses = commonClasses === null ? new Set(cs) : new Set(Array.from(commonClasses).filter(function(c){ return cs.indexOf(c) >= 0; }));
    });
    var cls = Array.from(commonClasses || []);
    if (tags.size === 1 && cls.length){
      return Array.from(tags)[0] + '.' + cls.join('.');
    } else if (tags.size === 1){
      return Array.from(tags)[0];
    } else if (cls.length){
      return '.' + cls.join('.');
    }
    return selectorFor(el) + ' > *';
  }

  // ── 多选公共部分分析 ──────────────────────────────
  function commonAncestor(elements){
    if (!elements.length) return null;
    var anc = elements[0].parentElement;
    while (anc){
      var ok = true;
      for (var i = 0; i < elements.length; i++){
        if (!anc.contains(elements[i])){ ok = false; break; }
      }
      if (ok) return anc;
      anc = anc.parentElement;
    }
    return null;
  }
  function arrayUnique(arr){ return Array.from(new Set(arr)); }
  function finalizeMulti(){
    var els = Array.from(window.__yzMulti);
    if (!els.length) return null;
    if (els.length === 1){
      return { mode: 'single', selector: selectorFor(els[0]), text: (els[0].innerText||'').trim().slice(0,200) };
    }
    var tags = new Set(), commonClasses = null, anyEmpty = false;
    els.forEach(function(el){
      tags.add(el.tagName.toLowerCase());
      if (el.classList.length === 0) anyEmpty = true;
      var cs = Array.from(el.classList);
      commonClasses = commonClasses === null ? new Set(cs) : new Set(Array.from(commonClasses).filter(function(c){ return cs.indexOf(c) >= 0; }));
    });
    var cls = Array.from(commonClasses || []);
    var sel = null;
    if (!anyEmpty && cls.length){
      sel = (tags.size === 1) ? (Array.from(tags)[0] + '.' + cls.join('.')) : ('.' + cls.join('.'));
    } else if (tags.size === 1 && !anyEmpty){
      sel = Array.from(tags)[0];
    }
    if (!sel){
      var anc = commonAncestor(els);
      var allDirect = anc && els.every(function(el){ return el.parentElement === anc; });
      if (allDirect){
        var childSel = arrayUnique(els.map(function(el){ return basicSelector(el); }));
        sel = (childSel.length === 1) ? (selectorFor(anc) + ' > ' + childSel[0])
                                      : els.map(function(el){ return selectorFor(el); }).join(', ');
      } else {
        sel = els.map(function(el){ return selectorFor(el); }).join(', ');
      }
    }
    return { mode: 'list', selector: sel, text: '已选 ' + els.length + ' 个元素' };
  }

  function outline(el, color){
    if (color){
      el.style.outline = '2px solid ' + color;
      el.style.outlineOffset = '-2px';
    } else {
      el.style.outline = '';
      el.style.outlineOffset = '';
    }
  }
  function resetHover(e){
    if (window.__yzHover && window.__yzHover !== e && window.__yzMulti.indexOf(window.__yzHover) < 0)
      outline(window.__yzHover, null);
    window.__yzHover = e;
    outline(e, '#ff9800');
  }
  function clearHover(){
    if (window.__yzHover){ outline(window.__yzHover, null); window.__yzHover = null; }
  }
  function refreshMultiOutlines(){
    window.__yzMulti.forEach(function(el){ outline(el, '#2e7d32'); });
  }
  function onOver(ev){
    if (!window.__yzMode) return;
    var el = ev.target;
    if (el === document.body) return;
    if (window.__yzMode === 'multi' && window.__yzMulti.indexOf(el) >= 0) return;
    resetHover(el);
    ev.preventDefault();
  }
  function onOut(){
    if (window.__yzMode) clearHover();
  }
  function onClick(ev){
    if (!window.__yzMode) return;
    ev.preventDefault(); ev.stopPropagation();
    var el = ev.target;
    if (el === document.body) return;
    if (window.__yzMode === 'multi'){
      var i = window.__yzMulti.indexOf(el);
      if (i >= 0){ window.__yzMulti.splice(i, 1); outline(el, null); }
      else {
        window.__yzMulti.push(el);
        outline(el, '#2e7d32');
      }
      return;  // 继续多选，直到用户点击“生成”
    }
    if (window.__yzMode === 'single'){
      window.__yzResult = { mode: 'single', selector: selectorFor(el), text: (el.innerText||'').trim().slice(0,200) };
    } else if (window.__yzMode === 'list'){
      window.__yzResult = { mode: 'list', selector: childrenSelector(el), text: (el.innerText||'').trim().slice(0,200) };
    } else if (window.__yzMode === 'keyword'){
      window.__yzResult = { mode: 'single', selector: selectorFor(el), text: (el.innerText||'').trim().slice(0,200) };
    }
    window.__yzMode = null;
    clearHover();
    window.__yzDone = true;
  }

  function highlightKeyword(kw){
    clearKeywordHighlights();
    if (!kw) return;
    var regex = new RegExp(escapeRegExp(kw), 'i');
    document.querySelectorAll('body *').forEach(function(el){
      if (el.children.length) return;
      var t = el.innerText || '';
      if (regex.test(t) && /^[\w-]+$/.test(el.tagName.toLowerCase())){
        el.style.outline = '1px dashed #42a5f5';
        el.style.outlineOffset = '-1px';
        el.__yzKwHit = true;
      }
    });
  }
  function clearKeywordHighlights(){
    document.querySelectorAll('body *').forEach(function(el){
      if (el.__yzKwHit){ el.style.outline=''; el.style.outlineOffset=''; el.__yzKwHit=false; }
    });
  }
  function escapeRegExp(s){ return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'); }

  window.__yzStart = function(mode, kw){
    window.__yzDone = false;
    window.__yzResult = null;
    window.__yzMode = mode;
    if (mode === 'multi') window.__yzMulti = [];
    if (mode === 'keyword' && kw) highlightKeyword(kw);
    document.addEventListener('mouseover', onOver, true);
    document.addEventListener('mouseout', onOut, true);
    document.addEventListener('click', onClick, true);
    document.body.style.cursor = 'crosshair';
  };
  window.__yzStop = function(){
    window.__yzMode = null;
    highlightKeyword('');
    clearHover();
    refreshMultiOutlines();
    document.removeEventListener('mouseover', onOver, true);
    document.removeEventListener('mouseout', onOut, true);
    document.removeEventListener('click', onClick, true);
    document.body.style.cursor = '';
  };
  window.__yzTogglePickMode = function(mode, kw){
    window.__yzStop();
    if (mode) window.__yzStart(mode, kw || null);
  };
  window.__yzFinalizeMulti = function(){
    var r = finalizeMulti();
    window.__yzResult = r;
    window.__yzMulti = [];
    refreshMultiOutlines();
    window.__yzDone = !!(r && r.selector);
  };
  window.__yzMultiCount = function(){ return window.__yzMulti.length; };
  window.__yzClearMulti = function(){
    window.__yzMulti.forEach(function(el){ outline(el, null); });
    window.__yzMulti = [];
  };
})();
"""


class PageSelectorDialog(QtWidgets.QDialog):
    """浏览器式元素选择器对话框。"""

    def __init__(self, url, parent=None, initial_options=None):
        super().__init__(parent)
        self.setWindowTitle("页面元素选择器")
        self.resize(1100, 760)
        self._url = url or ""
        self._options = dict(initial_options or {})
        self._poll = None
        self._last_selector = self._options.get("selector", "")
        self._in_multi = False

        if _webengine_view() is None:  # pragma: no cover
            self._webengine_error = True
            root = QtWidgets.QVBoxLayout(self)
            lbl = QtWidgets.QLabel("QtWebEngine 组件不可用，无法打开页面选择器。\n"
                                   "请确认已安装 PySide6 的 WebEngine 支持。")
            lbl.setWordWrap(True)
            root.addWidget(lbl)
            btn = QtWidgets.QPushButton("关闭")
            btn.clicked.connect(self.reject)
            root.addWidget(btn, 0, QtCore.Qt.AlignRight)
            return
        self._webengine_error = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 工具栏（模式按钮）──────────────────────────
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(8, 6, 8, 4)
        toolbar.setSpacing(6)

        self.btn_single = QtWidgets.QPushButton("选元素")
        self.btn_single.setCheckable(True)
        self.btn_single.clicked.connect(lambda: self._pick("single"))
        toolbar.addWidget(self.btn_single)

        self.btn_list = QtWidgets.QPushButton("列表容器")
        self.btn_list.setCheckable(True)
        self.btn_list.clicked.connect(lambda: self._pick("list"))
        toolbar.addWidget(self.btn_list)

        self.btn_multi = QtWidgets.QPushButton("多选")
        self.btn_multi.setCheckable(True)
        self.btn_multi.clicked.connect(lambda: self._pick("multi"))
        toolbar.addWidget(self.btn_multi)

        self.lb_multi_count = QtWidgets.QLabel("")
        toolbar.addWidget(self.lb_multi_count)

        self.btn_multi_gen = QtWidgets.QPushButton("生成多选")
        self.btn_multi_gen.setStyleSheet("color:#2e7d32;")
        self.btn_multi_gen.clicked.connect(self._finalize_multi)
        self.btn_multi_gen.setVisible(False)
        toolbar.addWidget(self.btn_multi_gen)

        toolbar.addSpacing(8)
        self.kw_input = QtWidgets.QLineEdit()
        self.kw_input.setPlaceholderText("关键词：高亮包含文字的块，再点选一个")
        self.kw_input.setMaximumWidth(200)
        self.kw_input.returnPressed.connect(lambda: self._start_keyword())
        toolbar.addWidget(self.kw_input)
        self.btn_kw = QtWidgets.QPushButton("关键词高亮")
        self.btn_kw.clicked.connect(self._start_keyword)
        toolbar.addWidget(self.btn_kw)

        toolbar.addStretch(1)

        self.btn_test = QtWidgets.QPushButton("测试匹配")
        self.btn_test.clicked.connect(self._test_match)
        toolbar.addWidget(self.btn_test)

        self.lb_count = QtWidgets.QLabel("")
        toolbar.addWidget(self.lb_count)

        self.btn_preview = QtWidgets.QPushButton("抓取预览")
        self.btn_preview.clicked.connect(self._preview_extract)
        toolbar.addWidget(self.btn_preview)

        root.addLayout(toolbar)

        # ── 选择器输入行 ───────────────────────────────
        sel_row = QtWidgets.QHBoxLayout()
        sel_row.setContentsMargins(8, 2, 8, 4)
        sel_row.addWidget(QtWidgets.QLabel("选择器"))
        self.selector_input = QtWidgets.QLineEdit()
        self.selector_input.setPlaceholderText("CSS 选择器（可手输/编辑，支持逗号组合、tag、.class、#id、[attr]、>、:nth-child）")
        self.selector_input.setText(self._last_selector)
        sel_row.addWidget(self.selector_input, 1)
        btn_use_sel = QtWidgets.QPushButton("应用选择器")
        btn_use_sel.clicked.connect(self._apply_manual_selector)
        sel_row.addWidget(btn_use_sel)
        root.addLayout(sel_row)

        # ── 状态行（可换行，不撑宽窗口）──────────────
        status_row = QtWidgets.QVBoxLayout()
        status_row.setContentsMargins(8, 0, 8, 2)
        self.mode_label = QtWidgets.QLabel("")
        self.mode_label.setWordWrap(True)
        self.mode_label.setStyleSheet("color:#666; background: rgba(0,0,0,0.03); padding:4px 6px;")
        self.mode_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        status_row.addWidget(self.mode_label)
        root.addLayout(status_row)

        # ── 导航行 ─────────────────────────────────────
        nav = QtWidgets.QHBoxLayout()
        nav.setContentsMargins(8, 2, 8, 2)
        self.in_url = QtWidgets.QLineEdit(self._url)
        self.in_url.returnPressed.connect(self._load)
        nav.addWidget(self.in_url, 1)
        btn_go = QtWidgets.QPushButton("打开")
        btn_go.clicked.connect(self._load)
        nav.addWidget(btn_go)
        root.addLayout(nav)

        self.web = _webengine_view()(self)
        root.addWidget(self.web, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(8, 6, 8, 6)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("完成")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._finish)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

        self.web.loadFinished.connect(self._on_loaded)
        if self._url:
            self.web.load(QtCore.QUrl(self._url))

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
            from .rss_store import _build_dom, find_elements
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
        from .rss_store import _detect_encoding
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
