"""页面选择器注入浏览器端的 JS：点选/多选/关键词高亮/选择器生成逻辑。"""

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
