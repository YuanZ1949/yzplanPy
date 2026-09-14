"""RSS 聚合文本/样式辅助：主题色板、关键词解析、HTML 消毒。"""

import datetime
import difflib
import html.parser
import re
from collections import Counter
from typing import Any

def rss_palette():
    """RSS 聚合模块主题色板：直接引用全局 theme_palette() 的 rss_* 键。

    半透明背景保证文字清晰且壁纸可见；无壁纸时也回退为接近全局 QSS 的面板观感。
    """
    from core.theme.tokens import theme_palette
    return dict(theme_palette())


def rss_style_vars():
    """rss_palette + sizing 合并字典，供 QSS format(**vars) 使用（颜色与尺寸令牌同源）。"""
    from core.theme.tokens import sizing
    c = rss_palette()
    c.update(sizing())
    return c


def rss_panel_palette():
    """兼容旧用法：只返回页面板背景色三项。"""
    c = rss_palette()
    return {"panel": c["rss_panel"], "panel_soft": c["rss_panel_soft"], "border": c["rss_border"]}


_QF = None


def _qf() -> dict[str, Any]:
    """按需导入并缓存 qfluentwidgets 组件/图标，避免拖慢模块导入。"""
    global _QF
    if _QF is None:
        from qfluentwidgets import (  # noqa: F401
            CaptionLabel, CheckBox, ComboBox, DropDownPushButton, FluentIcon,
            IconWidget, PrimaryDropDownPushButton, PushButton, PrimaryPushButton,
            PrimaryToolButton, RoundMenu, SearchLineEdit, StrongBodyLabel, ToggleButton,
            ToolButton, TransparentToolButton,
        )
        _QF = dict(
            CaptionLabel=CaptionLabel, CheckBox=CheckBox, ComboBox=ComboBox,
            DropDownPushButton=DropDownPushButton, FluentIcon=FluentIcon,
            IconWidget=IconWidget, PrimaryDropDownPushButton=PrimaryDropDownPushButton,
            PushButton=PushButton, PrimaryPushButton=PrimaryPushButton,
            PrimaryToolButton=PrimaryToolButton,
            RoundMenu=RoundMenu, SearchLineEdit=SearchLineEdit,
            StrongBodyLabel=StrongBodyLabel,
            ToggleButton=ToggleButton, ToolButton=ToolButton,
            TransparentToolButton=TransparentToolButton,
        )
    return _QF


def _parse_keywords(text):
    """把用户输入的关键词文本（逗号/空格/换行分隔）解析为去重后的列表。"""
    parts = []
    for raw in re.split(r"[,，\s]+", text or ""):
        tok = raw.strip()
        if tok and tok not in parts:
            parts.append(tok)
    return parts


# ── 预览 HTML 白名单净化（标准库）──────────────
_ALLOWED_TAGS = {
    "p", "br", "b", "strong", "i", "em", "u", "s", "strike", "sub", "sup",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "blockquote", "pre", "code", "hr", "div", "span", "table", "thead",
    "tbody", "tr", "th", "td", "caption",
    "a", "img", "figure", "figcaption", "audio", "video", "source",
}
_ALLOWED_ATTRS = {"href", "src", "title", "alt", "width", "height", "colspan", "rowspan", "controls", "poster", "loop", "muted"}
_URL_ATTRS = {"href": "http", "src": "http", "poster": "http"}
# 连同内容一起整体移除的危险/无关标签
_SKIP_TAGS = {
    "script", "style", "iframe", "object", "embed", "form", "input",
    "button", "svg", "math", "link", "meta", "base", "noscript", "template",
}
# HTML 空元素：无内容、无结束标签
_VOID_TAGS = {
    "br", "hr", "img", "source", "input", "meta", "link", "area",
    "base", "col", "wbr", "param", "track", "embed",
}


class _Sanitizer(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._stack = []  # 记录已开放的非 void 标签帧: (kind, tag)

    @staticmethod
    def _clean_attrs(attrs):
        cleaned = []
        for key, val in attrs:
            key = key.lower()
            if key not in _ALLOWED_ATTRS or key.startswith("on"):
                continue
            val = (val or "").strip()
            if key in _URL_ATTRS:
                low = val.lower()
                if not (low.startswith(("http:", "https:", "//", "/")) or low.startswith("data:image/")):
                    continue
            cleaned.append((key, val))
        return "".join(f' {k}="{_Sanitizer._escape_attr(v)}"' for k, v in cleaned)

    @staticmethod
    def _escape_attr(v):
        return (v or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        is_void = tag in _VOID_TAGS
        if tag in _SKIP_TAGS:
            if not is_void:
                self._stack.append(("skip", tag))
            return
        if tag not in _ALLOWED_TAGS:
            if not is_void:
                self._stack.append(("omit", tag))
            return
        if not is_void:
            kind = "a" if tag == "a" else "normal"
            self._stack.append((kind, tag))
        self.out.append(f"<{tag}{self._clean_attrs(attrs)}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_TAGS or tag not in _ALLOWED_TAGS:
            return
        self.out.append(f"<{tag}{self._clean_attrs(attrs)}/>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _VOID_TAGS or not self._stack:
            return
        kind, t = self._stack.pop()
        if kind == "skip":
            return
        if t == tag and tag in _ALLOWED_TAGS:
            self.out.append(f"</{t}>")

    def handle_data(self, data):
        if any(kind == "skip" for kind, _t in self._stack):
            return
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")


def _sanitize_html(src):
    """净化不可信的 HTML（RSS 描述/网页内容），仅保留白名单标签与安全属性。"""
    if not src:
        return ""
    p = _Sanitizer()
    try:
        p.feed(src)
        p.close()
    except Exception:
        return ""
    return "".join(p.out)


# ── 相似性聚合（二级聚合）──────────────────────────────
_WORD_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+")


def _norm_text(text):
    """归一化文本用于相似度比较：小写、去标点、拆词。"""
    return _WORD_RE.findall((text or "").lower())


def _title_similarity(a, b):
    """两条目标题的相似度（0~1）：difflib 序列匹配 + 词重叠加权。"""
    na = _norm_text(a)
    nb = _norm_text(b)
    if not na or not nb:
        return 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    inter = len(set(na) & set(nb))
    overlap = (2.0 * inter) / (len(set(na)) + len(set(nb))) if (set(na) or set(nb)) else 0.0
    return max(seq, overlap)


def _title_similarity_tokens(na, na_set, nb, nb_set):
    """预归一化 token 版本的相似度（_cluster_by_similarity 内部用，避免重复分词/建集）。

    与 _title_similarity 结果一致，但 na/nb 及对应 set 由调用方预计算并复用。
    """
    if not na or not nb:
        return 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    inter = len(na_set & nb_set)
    overlap = (2.0 * inter) / (len(na_set) + len(nb_set)) if (na_set or nb_set) else 0.0
    return max(seq, overlap)


def _cluster_by_similarity_gen(items, threshold=0.55):
    """贪心聚类的生成器版本：每处理完一个条目 yield 一次当前进度。

    与 _cluster_by_similarity 结果完全一致，但允许调用方在条目之间让出
    事件循环（分块渲染），避免大数据量下长时间阻塞 GUI 主线程。
    yield 值 = 已处理条目数（供进度显示）。
    """
    clusters = []
    cluster_tokens = []   # 与 clusters 平行：[(na, na_set)]，簇代表标题的归一化 token
    token_index = {}      # token -> set(cluster_idx)
    for idx, it in enumerate(items):
        title = (it.get("title") or "").strip() or (it.get("link") or "")
        na = _norm_text(title)
        na_set = set(na)
        best_idx = -1
        best_score = 0.0
        if na_set:
            cands = set()
            for t in na_set:
                cands.update(token_index.get(t, ()))
            for i in sorted(cands):
                cb_na, cb_set = cluster_tokens[i]
                score = _title_similarity_tokens(na, na_set, cb_na, cb_set)
                if score > best_score:
                    best_score = score
                    best_idx = i
        if best_idx >= 0 and best_score >= threshold:
            clusters[best_idx]["items"].append(it)
        else:
            clusters.append({"title": title, "items": [it]})
            cluster_tokens.append((na, na_set))
            ci = len(clusters) - 1
            for t in na_set:
                token_index.setdefault(t, set()).add(ci)
        yield idx + 1
    for cl in clusters:
        cl["items"].sort(key=lambda x: (x.get("published") or ""), reverse=True)
    return clusters


def _cluster_by_similarity(items, threshold=0.55):
    """把条目按标题相似度聚成若干簇（二级聚合）。

    贪心聚类：每条目与已有簇的代表标题比较，相似度 >= threshold 则并入该簇，
    否则新建簇。返回 [{title, items:[...]}, ...]，簇内按发布时间倒序。
    用标准库 difflib，不引入新依赖。

    性能优化（与朴素 O(n·k) 全量比较结果完全一致）：
    - 每条目/每簇的归一化 token 只计算一次并缓存（避免每次比较重复分词）。
    - 倒排索引 token -> {簇号}：相似度为 0 当且仅当两标题无共享 token
      （seq 与 overlap 均为 0），因此只与共享 >=1 个 token 的候选簇比较即可，
      跳过其余零相似度比较。候选簇按簇号升序遍历，保持与全量比较一致的
      「首个最高分簇胜出」平局规则。
    - 同步包装 _cluster_by_similarity_gen：一次性消费生成器，返回最终簇列表。
    """
    gen = _cluster_by_similarity_gen(items, threshold)
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


# ── 关键词自动提取 ────────────────────────────────────────────
_STOP_WORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with",
    "的", "了", "是", "在", "和", "与", "及", "或", "对", "为", "等", "下", "上",
}


def _extract_keywords(texts, top_n=10):
    """从文本列表中自动提取高频关键词，用于聚合对话框自动填充必须关键词。

    对每条文本用 _WORD_RE 分词，统计全局词频后过滤短词（len<2）、纯数字
    及停用词，返回频次最高的 top_n 个词（频次相同按首次出现顺序稳定）。
    """
    counter = Counter()
    for text in (texts or []):
        for w in _norm_text(text):
            if len(w) < 2 or w.isdigit() or w in _STOP_WORDS:
                continue
            counter[w] += 1
    # sorted 为稳定排序，同频词保持首次出现顺序
    return [w for w, _ in sorted(counter.items(), key=lambda x: -x[1])[:top_n]]


def analyze_high_freq_titles(titles, top_n=12):
    """从条目标题提取高频词供聚合对话框 chips 展示。"""
    return _extract_keywords(titles, top_n=top_n)


# ── 相对时间 ──────────────────────────────────────────────────

def _relative_time(ts):
    """把 ISO 时间戳转成相对时间文案（刚刚 / N 分钟前 / N 小时前 / N 天前）。

    兼容 SQLite datetime('now','localtime') 输出（无时区）与带 Z/偏移的 ISO 格式；
    解析失败返回空串（调用方自行决定是否展示）。
    """
    if not ts:
        return ""
    try:
        s = ts
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        delta = datetime.datetime.now() - dt
    except ValueError:
        return ""
    secs = delta.total_seconds()
    if secs < 60:
        return "刚刚"
    if secs < 3600:
        return f"{int(secs // 60)} 分钟前"
    if secs < 86400:
        return f"{int(secs // 3600)} 小时前"
    return f"{int(secs // 86400)} 天前"
