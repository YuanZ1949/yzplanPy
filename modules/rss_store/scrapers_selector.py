"""modules/rss_store slice: CSS selector engine.

Spliced from modules/rss_store.py by T13 codebase-reorg.
"""
import re
from .scrapers import (_build_dom, _inner_html, _inner_text, _walk,
                       _match_simple, _parse_simple, _split_top)


def _parse_selector(selector):
    """支持: 逗号组合、后代' '、子代'>'；返回一组 chain，每个 chain 为 [(token, 与上一个的组合器), ...]。"""
    groups = []
    for group in _split_top(selector, ","):
        chain = []
        comb = " "
        for part in re.split(r"\s+", group.strip()):
            if part == ">":
                comb = ">"
                continue
            if part:
                chain.append((_parse_simple(part), comb))
                comb = " "
        if chain:
            groups.append(chain)
    return groups


def _match_chain(groups, node):
    return any(_match_one_chain(chain, node) for chain in groups)


def _match_one_chain(chain, node):
    if not chain:
        return False
    tok, _comb = chain[-1]
    if not _match_simple(node, tok):
        return False
    cur = node.parent
    for tok, comb in reversed(chain[:-1]):
        if cur is None:
            return False
        if comb == ">":
            if not _match_simple(cur, tok):
                return False
            cur = cur.parent
        else:
            while cur is not None and not _match_simple(cur, tok):
                cur = cur.parent
            if cur is None:
                return False
            cur = cur.parent
    return True


def find_elements(dom, selector):
    if not selector or not selector.strip():
        return []
    groups = _parse_selector(selector)
    return [n for n in _walk(dom) if n.tag and n.tag != "#root" and _match_chain(groups, n)]


def _resolve_url(base, href):
    from urllib.parse import urljoin
    if not base or not href:
        return href or ""
    if href.startswith("//"):
        scheme = base.split(":", 1)[0] if ":" in base else "http"
        return scheme + ":" + href
    return urljoin(base, href)


def _value_from(node, spec, base_url):
    """按 spec 从元素提取字符串值。spec: {sel, attr, text}"""
    if not spec:
        return ""
    sel = spec.get("sel")
    attr = spec.get("attr")
    if sel:
        matches = find_elements(node, sel)
        target = matches[0] if matches else None
    else:
        target = node
    if target is None:
        return ""
    if attr:
        val = target.get(attr)
        if attr.lower() in ("href", "src") and val:
            return _resolve_url(base_url, val)
        return val or ""
    return _inner_text(target)


def _auto_link(node, base_url):
    """当 item.link 未指定时，自动为条目挑选对应元素的链接：
    元素本身是链接，或取其子树中第一个 <a href>；没有则返回空。"""
    if node is None:
        return ""
    href = node.get("href")
    if href:
        return _resolve_url(base_url, href)
    for n in _walk(node):
        if n is not node and n.tag == "a" and n.get("href"):
            return _resolve_url(base_url, n.get("href"))
    return ""


def scrape_html(html, options, base_url=""):
    """从 HTML 中按选项提取 RSS 条目。返回 entries 列表（与 fetch_feed 同结构）。"""
    if not html or not options:
        return []
    mode = options.get("mode", "list")
    selector = options.get("selector") or ""
    dom = _build_dom(html)
    nodes = find_elements(dom, selector)
    if not nodes:
        return []

    item_spec = options.get("item") or {}
    title_spec = item_spec.get("title") or {}
    link_spec = item_spec.get("link") or {}
    content_spec = item_spec.get("content") or {}
    max_items = int(options.get("max_items", 100) or 100)

    def make_entry(node):
        title = _value_from(node, title_spec, base_url) or _inner_text(node)
        link = _value_from(node, link_spec, base_url) or _auto_link(node, base_url)
        content = _value_from(node, content_spec, base_url)
        from datetime import datetime as _dt
        published = _dt.now().isoformat()
        image = ""
        img = next((n for n in _walk(node) if n.tag == "img"), None)
        if img is not None:
            src = img.get("src")
            if src:
                image = _resolve_url(base_url, src)
        return {
            "title": title,
            "link": link,
            "published": published,
            "description": content or _inner_html(node),
            "image_url": image,
        }

    entries = []
    if mode == "single":
        entries = [make_entry(nodes[0])] if nodes else []
    else:
        for n in nodes[:max_items]:
            entries.append(make_entry(n))
    entries = _filter_by_keywords(entries, options.get("keywords") or [])
    return entries


def _filter_by_keywords(entries, keywords):
    """关键词过滤：默认空列表接受全部；否则保留标题或描述包含任一关键词的条目。"""
    kws = [(k or "").strip().lower() for k in keywords]
    kws = [k for k in kws if k]
    if not kws:
        return entries
    result = []
    for e in entries:
        text = "{} {}".format(e.get("title", ""), e.get("description", "")).lower()
        if any(k in text for k in kws):
            result.append(e)
    return result
