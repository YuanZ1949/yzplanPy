"""RSS 聚合文本/样式辅助：主题色板、关键词解析、HTML 消毒。"""

import difflib
import html.parser
import re
from typing import Any

def _rss_colors():
    """一组主题感知的 RSS 样式色板（明暗两套），供各处列表/按钮/标签统一取色。

    半透明背景保证文字清晰且壁纸可见；无壁纸时也回退为接近全局 QSS 的面板观感。
    """
    try:
        from core.theme import resolve_dark
        dark = resolve_dark("auto")
    except Exception:
        dark = True
    if dark:
        return {
            "dark": True,
            "panel": "rgba(24,24,27,0.74)",
            "panel_soft": "rgba(24,24,27,0.64)",
            "panel_card": "rgba(255,255,255,0.05)",
            "border": "rgba(255,255,255,0.08)",
            "border_strong": "rgba(255,255,255,0.16)",
            # 主强调色
            "accent": "#4aa3ff",
            "accent_hover": "#6eb6ff",
            "accent_pressed": "#2f8ae6",
            "accent_bg": "rgba(74,163,255,0.16)",
            # 文字
            "text": "#e8e8e8",
            "text_secondary": "#9a9a9a",
            "text_faint": "#76767a",
            "title_unread": "#ffffff",
            "title_read": "#8a8a8a",
            # 控件（按钮/输入/下拉）
            "control_bg": "rgba(255,255,255,0.09)",
            "control_bg_hover": "rgba(255,255,255,0.12)",
            "control_border": "rgba(255,255,255,0.10)",
            "control_border_hover": "rgba(255,255,255,0.22)",
            # 标签药丸
            "pill_tag_bg": "rgba(74,163,255,0.18)",
            "pill_tag_fg": "#8fc2ff",
            "pill_torrent_bg": "rgba(255,107,107,0.16)",
            "pill_torrent_fg": "#ff9a9a",
            "pill_article_bg": "rgba(37,205,150,0.16)",
            "pill_article_fg": "#7fe0c0",
            # 徽标/收藏
            "badge_bg": "rgba(74,163,255,0.22)",
            "badge_fg": "#9cc8ff",
            "fav_color": "#ffc107",
            # 列表行
            "row_hover": "rgba(255,255,255,0.05)",
            "row_selected": "rgba(0,120,215,0.30)",
            # 玻璃面板 / 分隔 / 未读圆点
            "header_bg": "rgba(255,255,255,0.05)",
            "header_border": "rgba(255,255,255,0.10)",
            "card_border": "rgba(255,255,255,0.10)",
            "divider": "rgba(255,255,255,0.06)",
            "dot_unread": "#4aa3ff",
            "dot_read": "rgba(255,255,255,0.16)",
            # 分组 / 卡片 / 控件容器 / 选择态（perf 语言对称，T1 新增）
            "group_border": "rgba(255,255,255,0.12)",
            "group_bg": "rgba(255,255,255,0.04)",
            "card_bg": "rgba(255,255,255,0.05)",
            "ctrl_bg": "rgba(255,255,255,0.05)",
            "ctrl_border": "rgba(255,255,255,0.10)",
            "grid_color": "rgba(255,255,255,0.06)",
            "sel_bg": "rgba(0,120,215,0.25)",
            "text_primary": "#e8e8e8",
            "btn_group_bg": "rgba(255,255,255,0.04)",
            "btn_group_border": "rgba(255,255,255,0.08)",
            "menu_bg": "rgba(42,42,44,0.94)",
            "menu_border": "rgba(255,255,255,0.10)",
            "menu_item_hover": "rgba(255,255,255,0.08)",
            "menu_item_selected": "rgba(74,163,255,0.25)",
            # 侧栏彩色徽章（v4 设计）
            "badge": {
                "all": {"bg": "rgba(74,163,255,0.38)", "fg": "#c4deff"},
                "unread": {"bg": "rgba(37,205,150,0.35)", "fg": "#a8f0d8"},
                "fav": {"bg": "rgba(255,193,7,0.32)", "fg": "#ffe88a"},
                "torrent": {"bg": "rgba(255,107,107,0.34)", "fg": "#ffb8b8"},
                "agg": {"bg": "rgba(160,107,255,0.36)", "fg": "#d8c8ff"},
                "feed": {"bg": "rgba(255,255,255,0.28)", "fg": "#e8e8ec"},
            },
        }
    return {
        "dark": False,
        "panel": "rgba(247,247,250,0.90)",
        "panel_soft": "rgba(248,248,251,0.86)",
        "panel_card": "rgba(255,255,255,0.96)",
        "border": "rgba(0,0,0,0.10)",
        "border_strong": "rgba(0,0,0,0.16)",
        "accent": "#1178e0",
        "accent_hover": "#0d5cb8",
        "accent_pressed": "#0a4a96",
        "accent_bg": "rgba(17,120,224,0.10)",
        "text": "#1f1f1f",
        "text_secondary": "#666666",
        "text_faint": "#999999",
        "title_unread": "#111111",
        "title_read": "#9a9a9a",
        "control_bg": "rgba(255,255,255,0.98)",
        "control_bg_hover": "rgba(0,0,0,0.06)",
        "control_border": "rgba(0,0,0,0.10)",
        "control_border_hover": "rgba(0,0,0,0.16)",
        "pill_tag_bg": "#e8f0fe",
        "pill_tag_fg": "#1967d2",
        "pill_torrent_bg": "#fce8e6",
        "pill_torrent_fg": "#c5221f",
        "pill_article_bg": "#e6f4ea",
        "pill_article_fg": "#137333",
        "badge_bg": "#e8f0fe",
        "badge_fg": "#1967d2",
        "fav_color": "#ffb300",
        "row_hover": "rgba(0,120,215,0.06)",
        "row_selected": "rgba(0,120,215,0.16)",
        "header_bg": "rgba(255,255,255,0.72)",
        "header_border": "rgba(0,0,0,0.10)",
        "card_border": "rgba(0,0,0,0.10)",
        "divider": "rgba(0,0,0,0.06)",
        "dot_unread": "#1178e0",
        "dot_read": "rgba(0,0,0,0.16)",
        "group_border": "rgba(0,0,0,0.10)",
        "group_bg": "rgba(0,0,0,0.02)",
        "card_bg": "rgba(255,255,255,0.96)",
        "ctrl_bg": "rgba(255,255,255,0.98)",
        "ctrl_border": "rgba(0,0,0,0.10)",
        "grid_color": "rgba(0,0,0,0.06)",
        "sel_bg": "rgba(0,120,215,0.16)",
        "text_primary": "#1f1f1f",
        "btn_group_bg": "rgba(0,0,0,0.03)",
        "btn_group_border": "rgba(0,0,0,0.08)",
        "menu_bg": "rgba(252,252,252,0.98)",
        "menu_border": "rgba(0,0,0,0.10)",
        "menu_item_hover": "rgba(0,0,0,0.05)",
        "menu_item_selected": "rgba(17,120,224,0.16)",
        "badge": {
            "all": {"bg": "#e8f0fe", "fg": "#1967d2"},
            "unread": {"bg": "#e6f4ea", "fg": "#137333"},
            "fav": {"bg": "#fff6dd", "fg": "#b26a00"},
            "torrent": {"bg": "#fce8e6", "fg": "#c5221f"},
            "agg": {"bg": "#f0eaff", "fg": "#6a3fd8"},
            "feed": {"bg": "rgba(0,0,0,0.06)", "fg": "#5f6368"},
        },
    }


def _rss_panel_colors():
    """兼容旧用法：只返回页面板背景色三项。"""
    c = _rss_colors()
    return {"panel": c["panel"], "panel_soft": c["panel_soft"], "border": c["border"]}


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
