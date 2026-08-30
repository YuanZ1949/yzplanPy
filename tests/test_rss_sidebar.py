"""RSS 侧边栏 / 聚合 / hash 扫描 相关的数据层与 UI 离屏测试。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from modules.rss_store import RssStore, extract_btih
from modules import rss_aggregator as m


_MAG_A = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=one"
_MAG_B = "magnet:?xt=urn:btih:" + "b" * 40 + "&dn=two"


def _make_store(tmp_path):
    return RssStore(str(tmp_path / "s.db"))


class FakeConfig(dict):
    def __init__(self):
        super().__init__()
        self._data = {}

    def get(self, key, default=None):
        dct = {**self._data, **dict(self)}
        return dct.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def unset(self, key):
        self._data.pop(key, None)


class FakeCtx:
    def __init__(self):
        self.config = FakeConfig()


class FakeOwner:
    def __init__(self, store):
        self.store = store
        self.context = FakeCtx()
        self._scan_calls = 0
        self._icon_calls = 0

    def scan_hashes(self, limit=200):
        self._scan_calls += 1

    def refresh_favicons(self):
        self._icon_calls += 1


def _seed_sidebar(store):
    store.add_feed("站点A", "https://a.example/rss", tag="tA")
    store.add_feed("站点B", "https://b.example/rss", tag="tB")
    fid = {f["name"]: f["id"] for f in store.list_feeds()}
    fa, fb = fid["站点A"], fid["站点B"]
    store.update_feed_refresh_time(fa)
    store.update_feed_refresh_time(fb)
    store.ingest("tA", [{"title": "Magnet one", "link": _MAG_A, "published": "2026-01-01", "description": "", "image_url": ""}], feed_id=fa)
    store.ingest("tB", [{"title": "Magnet two", "link": _MAG_A.replace("dn=one", "dn=A2"), "published": "2026-01-02", "description": "", "image_url": ""}], feed_id=fb)
    store.ingest("tB", [{"title": "Magnet B", "link": _MAG_B, "published": "2026-01-03", "description": "", "image_url": ""}], feed_id=fb)
    store.ingest("tA", [{"title": "普通文章", "link": "https://a.example/post/1", "published": "2026-01-04", "description": "内有 python 关键词", "image_url": ""}], feed_id=fa)

    # 手动聚合
    aid = store.add_aggregation("聚合A", agg_type="mixed", feed_ids=[fa])
    store.refresh_aggregation(aid)
    kw = store.add_aggregation("关键词聚合", agg_type="keyword", kw_required=["python"])
    store.refresh_aggregation(kw)
    tor = store.add_aggregation("磁链聚合", agg_type="torrent", feed_ids=[fa, fb])
    store.refresh_aggregation(tor)
    return fa, fb, aid, kw, tor


# ── 数据层：extract_btih ─────────────────────────────────────

def test_extract_btih_magnet():
    h = extract_btih("magnet:?xt=urn:btih:" + "A" * 40 + "&dn=x&tr=udp://t")
    assert h == "a" * 40


def test_extract_btih_plain_40hex():
    assert extract_btih("c" * 40) == "c" * 40


def test_extract_btih_none():
    assert extract_btih("https://example.com/a?b=1") == ""
    assert extract_btih("") == ""


def test_extract_btih_base32():
    # 动漫花园等站点用 32 位 Base32 BTIH，应规范化为 40 位 hex
    assert extract_btih("magnet:?xt=urn:btih:T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C&dn=x") == "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"
    assert extract_btih("magnet:?xt=urn:btih:aaaa0" + "B" * 27) == ""
    # 大小写归一（base32 大小写无关）
    assert extract_btih("magnet:?xt=urn:btih:t4hjfgghgeeu7wxtanw27ptp77oq4r3c") == "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"
    assert len(extract_btih("magnet:?xt=urn:btih:" + "Q" * 32)) == 40


# ── 数据层：ingest 自动填 hash ───────────────────────────────

def test_ingest_fills_torrent_hash(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("f", "https://a.example/rss", tag="t")
    store.ingest("t", [{"title": "M", "link": _MAG_A, "published": "2026", "description": "", "image_url": ""}])
    it = store.recent(10)[0]
    assert it["torrent_hash"] == "a" * 40


# ── 数据层：recent 过滤 ──────────────────────────────────────

def test_recent_feed_ids_filter(tmp_path):
    store = _make_store(tmp_path)
    fa, fb, *_ = _seed_sidebar(store)
    only_a = store.recent(100, feed_ids=[fa])
    assert all(x["title"] in ("Magnet one", "普通文章") for x in only_a)
    assert "普通文章" in [x["title"] for x in only_a]
    # 精确到订阅源：站点A 不应包含站点B 的条目（哪怕同 tag）
    titles_a = {x["title"] for x in only_a}
    assert "Magnet two" not in titles_a
    assert "Magnet B" not in titles_a
    only_b = store.recent(100, feed_ids=[fb])
    assert {x["title"] for x in only_b} == {"Magnet two", "Magnet B"}


def test_recent_keyword_filter(tmp_path):
    store = _make_store(tmp_path)
    _seed_sidebar(store)
    res = store.recent(100, keyword="python")
    assert len(res) == 1
    assert res[0]["title"] == "普通文章"


def test_recent_torrent_hash_filter(tmp_path):
    store = _make_store(tmp_path)
    _seed_sidebar(store)
    res = store.recent(100, torrent_hash="a" * 40)
    assert len(res) == 2
    assert all(x["torrent_hash"] == "a" * 40 for x in res)
    res_b = store.recent(100, torrent_hash="b" * 40)
    assert len(res_b) == 1


# ── 数据层：list_sidebar ─────────────────────────────────────

def test_list_sidebar_shape(tmp_path):
    store = _make_store(tmp_path)
    _seed_sidebar(store)
    data = store.list_sidebar()
    assert len(data["feeds"]) == 2
    assert all(set(("id", "name", "tag", "icon", "unread", "created_at", "last_refresh")) <= set(f) for f in data["feeds"])
    aggs = {a["name"]: a for a in data["aggregations"]}
    assert set(aggs) == {"聚合A", "关键词聚合", "磁链聚合"}
    assert aggs["磁链聚合"]["agg_type"] == "torrent"
    # 磁链聚合 count = 3（magnet one/two/B 都命中 torrent 类型）
    assert aggs["磁链聚合"]["count"] == 3


def test_aggregation_keyword_tri_bucket(tmp_path):
    store = _make_store(tmp_path)
    _, _, *_ = _seed_sidebar(store)
    # 必须+禁止
    aid = store.add_aggregation("kw2", agg_type="keyword", kw_required=["python"], kw_forbidden=["helloworld"])
    store.refresh_aggregation(aid)
    assert [x["title"] for x in store.recent(100, agg_id=aid)] == ["普通文章"]
    # 必须不满足 → 空
    aid2 = store.add_aggregation("kw3", agg_type="keyword", kw_required=["不存在词"])
    store.refresh_aggregation(aid2)
    assert store.recent(100, agg_id=aid2) == []


def test_aggregation_torrent_groups(tmp_path):
    store = _make_store(tmp_path)
    _, _, _, _, tor = _seed_sidebar(store)
    groups = store.get_aggregation_torrent_groups(tor)
    by_hash = {g["hash"]: g for g in groups}
    assert "a" * 40 in by_hash and "b" * 40 in by_hash
    assert by_hash["a" * 40]["count"] == 2
    assert by_hash["a" * 40]["feed_count"] == 2
    items = store.get_aggregation_torrent_items(tor, "a" * 40)
    assert len(items) == 2


# ── 数据层：torrent links 缓存 + hash 扫描状态 ────────────────

def test_torrent_links_cache_dedup(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("f", "https://a.example/rss", tag="t")
    store.ingest("t", [{"title": "M", "link": _MAG_A, "published": "2026", "description": "", "image_url": ""}])
    h = store.recent(10)[0]["hash"]
    store.record_item_torrent_links(h, [_MAG_B, "https://z.example/x.torrent"])
    store.record_item_torrent_links(h, [_MAG_B])
    links = store.get_item_torrent_links(h)
    assert len(links) == 2
    assert _MAG_B in links
    it = store.get_item(h)
    assert it["torrent_hash"] == "b" * 40


def test_pending_hash_scan_magnet_only(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("f", "https://a.example/rss", tag="磁力站")
    store.ingest("磁力站", [{"title": "M", "link": _MAG_A, "published": "2026", "description": "", "image_url": ""}])
    store.ingest("磁力站", [{"title": "普通", "link": "https://a.example/x", "published": "2026", "description": "", "image_url": ""}])
    # _MAG_A 自带 btih → 不入待扫；但普通条目所在 tag 含“磁” → magnet_only 仍纳入扫描
    pend = store.get_pending_hash_scans(10, magnet_only=True)
    assert len(pend) == 1
    assert pend[0]["link"] == "https://a.example/x"
    store.mark_hash_scan([pend[0]["hash"]], 3)
    assert store.get_pending_hash_scans(10) == []


def test_pending_hash_scan_seedz_tag(tmp_path):
    # 种子 标签与 磁 统一处理：种子源的无 hash 条目也应被 magnet_only 纳入
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    store.set_feed_is_torrent(fid, 1)
    store.ingest("种子", [{"title": "无hash", "link": "https://a.example/x", "published": "2026", "description": "", "image_url": ""}], feed_id=fid)
    pend = store.get_pending_hash_scans(10, magnet_only=True)
    assert len(pend) == 1
    assert pend[0]["link"] == "https://a.example/x"


def test_pending_hash_scan_is_torrent_feed(tmp_path):
    # 标记为磁力/种子源的订阅源，其无 hash 条目会被 magnet_only 纳入（无需 tag 关键词）
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="普通")
    fid = store.list_feeds()[0]["id"]
    store.set_feed_is_torrent(fid, 1)
    store.ingest("普通", [{"title": "无hash", "link": "https://a.example/x", "published": "2026", "description": "", "image_url": ""}], feed_id=fid)
    pend = store.get_pending_hash_scans(10, magnet_only=True)
    assert len(pend) == 1


def test_ingest_base32_from_enclosure_hash(tmp_path):
    # 条目显式携带 base32 BTIH（RSS enclosure 解析结果）应入库
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    store.ingest("种子", [{"title": "M", "link": "https://a.example/detail",
                            "description": "", "image_url": "",
                            "torrent_hash": "T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C"}], feed_id=fid)
    it = store.recent(10)[0]
    assert it["torrent_hash"] == "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"


def test_ingest_backfills_existing_hash(tmp_path):
    # 旧条目先前入库无 hash，再次 ingest 同条目（带 hash）应回填 torrent_hash
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    entry = {"title": "M", "link": "https://a.example/x", "description": "", "image_url": ""}
    store.ingest("种子", [entry], feed_id=fid)
    it = store.recent(10)[0]
    assert it["torrent_hash"] == ""
    entry2 = dict(entry)
    entry2["torrent_hash"] = "T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C"
    store.ingest("种子", [entry2], feed_id=fid)
    it = store.recent(10)[0]
    assert it["torrent_hash"] == "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"


def test_ingest_same_torrent_hex_and_base32_merge(tmp_path):
    # 同一条目分别以 40 位 hex 与 32 位 base32 入库，规范化后应为同一 torrent_hash（能合并分组）
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    store.ingest("种子", [{"title": "M1", "link": "https://a.example/1",
                           "torrent_hash": "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"}], feed_id=fid)
    store.ingest("种子", [{"title": "M2", "link": "https://a.example/2",
                           "torrent_hash": "T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C"}], feed_id=fid)
    assert store.recent(100) != []
    torrent_hashes = {it["torrent_hash"] for it in store.recent(100)}
    assert torrent_hashes == {"9f0e9298c731094fdaf3036dafbe6fffdd0e4762"}


# ── 数据层：favicon 读写 ─────────────────────────────────────

def test_feed_icon_roundtrip(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("f", "https://a.example/rss", tag="t")
    fid = store.list_feeds()[0]["id"]
    store.set_feed_icon(fid, "base64:AAAA")
    assert store.get_feed_icon(fid) == "base64:AAAA"
    assert store.feeds_needing_favicon() == []  # state=2 不再抓


# ── UI 离屏：侧边栏 + 页面联动 ────────────────────────────────

def _build_page(tmp_path):
    store = _make_store(tmp_path)
    fa, fb, aid, kw, tor = _seed_sidebar(store)
    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)
    return store, owner, page


def _sidebar_data(page):
    out = []
    for i in range(page._sidebar.list.count()):
        out.append(page._sidebar.list.item(i).data(QtCore.Qt.UserRole))
    return out


def test_page_sidebar_build(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    # 平铺：全部 → 聚合(3) → 订阅源(2)
    kinds = [d.get("kind") for d in _sidebar_data(page)]
    assert kinds[0] == "all"
    assert kinds.count("agg") == 3
    assert kinds.count("feed") == 2


def test_page_select_feed_filters(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    fa_id = None
    for d in _sidebar_data(page):
        if d.get("kind") == "feed" and d["name"] == "站点A":
            fa_id = d["feed_id"]
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "feed" and d["feed_id"] == fa_id)
    sb.list.setCurrentRow(row)
    assert sb.current_filter() == {"feed_ids": [fa_id]}
    assert page.item_list.count() == 2  # 站点A：magnet one + 普通文章


def test_page_select_keyword_filters(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "agg" and d["name"] == "关键词聚合")
    sb.list.setCurrentRow(row)
    f = sb.current_filter()
    assert f.get("agg_id") is not None
    assert page.item_list.count() == 1


def test_page_select_torrent_filters(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "agg" and d["name"] == "磁链聚合")
    sb.list.setCurrentRow(row)
    f = sb.current_filter()
    assert f.get("agg_type") == "torrent"
    assert page.item_list.count() == 5  # 2 分组头 + 3 成员条目(magnet one/two/B)
    assert "磁链聚合" in page.lb_total.text()
    assert "2 个分组" in page.lb_total.text()


def test_torrent_group_collapse_expand(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "agg" and d["name"] == "磁链聚合")
    sb.list.setCurrentRow(row)
    head_hash = next(iter(page._group_children))
    page._toggle_torrent_group(head_hash)
    heads = page._group_children[head_hash]
    assert page.item_list.isRowHidden(page.item_list.row(heads[0])) is False


def test_sidebar_reload_preserves_selection(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "feed" and d["name"] == "站点A")
    sb.list.setCurrentRow(row)
    page._reload_sidebar()
    cur = sb.current_data()
    assert cur.get("kind") == "feed"
    assert cur.get("name") == "站点A"


def test_btih_migration_base32_to_hex(tmp_path):
    # 既有库中 32 位 base32 hash 在 store 重开时应就地迁移为 40 位 hex
    import sqlite3
    db = str(tmp_path / "s.db")
    store = RssStore(db)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    store.ingest("种子", [{"title": "M", "link": "https://a.example/1",
                           "torrent_hash": "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"}], feed_id=fid)
    # 直接往库里塞一条 base32 hash 旧数据
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO items(hash,title,link,published,description,image_url,torrent_hash) "
        "VALUES(?,?,?,?,?,?,?)",
        ("h32", "旧条目 base32", "https://a.example/2", "2026-01-01", "", "",
         "T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C"),
    )
    conn.commit()
    conn.close()
    # 重开触发迁移
    store2 = RssStore(db)
    by_hash = {it["torrent_hash"] for it in store2.recent(100)}
    assert "9f0e9298c731094fdaf3036dafbe6fffdd0e4762" in by_hash
    # 旧的 hex 条目保持不变
    assert "9f0e9298c731094fdaf3036dafbe6fffdd0e4762" in by_hash


def test_refresh_menu_multiselect_run(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    assert hasattr(sb, "btn_refresh_all")
    assert not hasattr(sb, "btn_scan_magnet")
    owner = page.owner
    base_scan, base_icon = owner._scan_calls, owner._icon_calls
    # 勾选 扫描磁力 + 刷新图标
    sb._refresh_actions["scan"].setChecked(True)
    sb._refresh_actions["icons"].setChecked(True)
    sb._run_selected_refresh()
    assert owner._scan_calls == base_scan + 1
    assert owner._icon_calls == base_icon + 1
    # 执行后清除勾选
    assert sb._refresh_ops["scan"] is False
    assert sb._refresh_ops["icons"] is False


def test_settings_dialog_no_hardcoded_theme(tmp_path):
    _, owner, page = _build_page(tmp_path)
    dlg = m._SettingsDialog(owner, page)
    ss = dlg.styleSheet()
    assert "#2c2c2c" not in ss
    assert "rgba(255,255,255,0.10)" not in ss
    assert "rgba(40,40,40,0.85)" not in ss
    dlg.close()


def test_agg_head_count_at_end_no_newline(tmp_path):
    # 磁链聚合 head 行：计数作为独立徽标放在行末(不换行)，标题可换行且不含计数
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "agg" and d["name"] == "磁链聚合")
    sb.list.setCurrentRow(row)
    heads = []
    for r in range(page.item_list.count()):
        it = page.item_list.item(r)
        w = page.item_list.itemWidget(it)
        if isinstance(w, m._HeadRow):
            heads.append(w)
    assert heads, "应存在磁链聚合 head 行"
    for w in heads:
        assert "来源" in w.count_label.text()  # 计数徽标含"来源"文案
        assert w.count_label.text().rstrip().endswith("来源")  # 来源计数在行末
        assert w.count_label.wordWrap() is False  # 计数不换行
        assert "\n" not in w.text()  # 标题文本无换行(交给 word-wrap)
        assert w.title_label.wordWrap() is True  # 标题允许换行
        assert "来源" not in w.text()  # 计数不应混进标题


def test_fetcher_process_feed_returns_dict_on_success(tmp_path):
    # 回归：抓取成功路径必须返回结果 dict，否则 worker 线程 r.get 崩溃
    store, _, _ = _build_page(tmp_path)
    f = dict(store.list_feeds()[0])
    f.setdefault("feed_type", "rss")
    f.setdefault("scrape_options", "{}")
    f.setdefault("rendered", False)
    f.setdefault("custom_headers", "{}")
    f.setdefault("etag", "")
    f.setdefault("last_modified", "")
    fet = m._Fetcher([f], store, "", 1, 1, 1)

    def fake_fetch(*a, **k):
        return ([{"title": "X", "link": "https://x/1", "description": "", "image_url": ""}], "", "etag1", "")

    orig = m.fetch_feed
    m.fetch_feed = fake_fetch
    try:
        r = fet._process_feed(f)
    finally:
        m.fetch_feed = orig
    assert isinstance(r, dict)
    for key in ("feed_id", "name", "tag", "total", "added", "error"):
        assert key in r