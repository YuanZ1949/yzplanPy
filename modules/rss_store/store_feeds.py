"""rss_store slice: feed management mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
import json

from core.perf import trace

from .store_conn import RssStoreBase


class FeedsMixin(RssStoreBase):
    # ── Feed 管理 ──────────────────────────────────────────────
    @trace()
    def list_feeds(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM feeds ORDER BY sort_order, group_name, name").fetchall()
            tag_rows = conn.execute("SELECT feed_id, tag FROM feed_tags ORDER BY feed_id, tag").fetchall()
        tags_map = {}
        for r in tag_rows:
            tags_map.setdefault(r["feed_id"], []).append(r["tag"])
        feeds = [dict(r) for r in rows]
        for f in feeds:
            f["tags"] = tags_map.get(f["id"], [])
        return feeds

    def list_feed_groups(self):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT group_name FROM feeds ORDER BY group_name"
            ).fetchall()
        return [r["group_name"] for r in rows if r["group_name"]]

    def add_feed(self, name, url, tag, group_name="", refresh_interval=1800, custom_headers=None, feed_type="normal", scrape_options=None, rendered=0, tags=None):
        tags = [t for t in (tags or ([tag] if tag else [name])) if t]
        first_tag = tags[0] if tags else (tag or name)
        with self._conn() as conn:
            # D8: 原 INSERT OR REPLACE 在同名源（name 唯一键）冲突时整行替换，
            # 静默重置 icon/etag/refresh_interval/created_at 等配置并更换 id（item_feeds 关联被孤立）。
            # 改为 ON CONFLICT DO UPDATE：保留原 id 与既有配置，仅更新调用方显式提供的定义字段。
            cur = conn.execute(
                """INSERT INTO feeds(name,url,tag,enabled,group_name,refresh_interval,custom_headers,feed_type,scrape_options,rendered,created_at)
                   VALUES(?,?,?,1,?,?,?,?,?,?,datetime('now','localtime'))
                   ON CONFLICT(name) DO UPDATE SET
                       url=excluded.url, tag=excluded.tag, enabled=1,
                       group_name=excluded.group_name,
                       custom_headers=excluded.custom_headers,
                       feed_type=excluded.feed_type,
                       scrape_options=excluded.scrape_options,
                       rendered=excluded.rendered""",
                (name, url, first_tag, group_name or "", refresh_interval, json.dumps(custom_headers or {}),
                 feed_type, json.dumps(scrape_options or {}), 1 if rendered else 0),
            )
            # D24: 返回新行 id（UPSERT 更新既有行时 lastrowid 为被更新行的 id），
            # 调用方可直接用作 feed_id，无需再回查。
            fid = cur.lastrowid
            if fid:
                conn.execute("DELETE FROM feed_tags WHERE feed_id=?", (fid,))
                conn.executemany(
                    "INSERT OR IGNORE INTO feed_tags(feed_id, tag) VALUES(?,?)",
                    [(fid, t) for t in tags],
                )
            return fid

    def update_feed(self, feed_id, **kwargs):
        allowed = {"name", "url", "tag", "enabled", "group_name", "refresh_interval", "custom_headers", "etag", "last_modified", "last_error", "error_count", "sort_order", "feed_type", "scrape_options", "rendered", "icon", "favicon_state"}
        if kwargs.get("scrape_options") is not None and not isinstance(kwargs.get("scrape_options"), str):
            kwargs["scrape_options"] = json.dumps(kwargs["scrape_options"])
        tags = kwargs.pop("tags", None)
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if tags is None and not updates:
            return
        if updates:
            sets = ", ".join(f"{k}=?" for k in updates)
            vals = list(updates.values()) + [feed_id]
            with self._conn() as conn:
                conn.execute(f"UPDATE feeds SET {sets} WHERE id=?", vals)
        if tags is not None:
            self.set_feed_tags(feed_id, tags)

    def remove_feed(self, feed_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM feeds WHERE id=?", (feed_id,))
            conn.execute("DELETE FROM feed_tags WHERE feed_id=?", (feed_id,))
            # D20: 级联清理 item_feeds，否则源范围查询(recent feed_ids=)仍含已删源的条目
            conn.execute("DELETE FROM item_feeds WHERE feed_id=?", (feed_id,))

    def set_feed_enabled(self, feed_id, enabled):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET enabled=? WHERE id=?", (1 if enabled else 0, feed_id))

    def set_feed_is_torrent(self, feed_id, is_torrent):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET is_torrent=? WHERE id=?", (1 if is_torrent else 0, feed_id))

    def get_feed_is_torrent(self, feed_id):
        with self._conn() as conn:
            row = conn.execute("SELECT is_torrent FROM feeds WHERE id=?", (feed_id,)).fetchone()
        return bool(row and row["is_torrent"])

    def set_feed_error(self, feed_id, error_msg):
        with self._conn() as conn:
            conn.execute(
                "UPDATE feeds SET last_error=?, error_count=error_count+1 WHERE id=?",
                (error_msg, feed_id),
            )

    def clear_feed_error(self, feed_id):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET last_error='', error_count=0 WHERE id=?", (feed_id,))

    def update_feed_order(self, feed_ids):
        with self._conn() as conn:
            for idx, fid in enumerate(feed_ids):
                conn.execute("UPDATE feeds SET sort_order=? WHERE id=?", (idx, fid))

    def get_feed_by_id(self, feed_id):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM feeds WHERE id=?", (feed_id,)).fetchone()
        d = dict(row) if row else None
        if d:
            d["tags"] = self.get_feed_tags(feed_id)
        return d

    def get_feed_tags(self, feed_id):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT tag FROM feed_tags WHERE feed_id=? ORDER BY tag", (feed_id,)
            ).fetchall()
        return [r["tag"] for r in rows]

    def set_feed_tags(self, feed_id, tags):
        tags = [t for t in (tags or []) if t]
        with self._conn() as conn:
            conn.execute("DELETE FROM feed_tags WHERE feed_id=?", (feed_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO feed_tags(feed_id, tag) VALUES(?,?)",
                [(feed_id, t) for t in tags],
            )
            legacy = tags[0] if tags else ""
            conn.execute("UPDATE feeds SET tag=? WHERE id=?", (legacy, feed_id))

    def update_feed_refresh_time(self, feed_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE feeds SET last_refresh=datetime('now','localtime') WHERE id=?",
                (feed_id,),
            )

    def get_feeds_needing_refresh(self):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM feeds
                WHERE enabled = 1 AND (
                    last_refresh IS NULL
                    OR datetime(last_refresh, '+' || refresh_interval || ' seconds') <= datetime('now','localtime')
                )
                ORDER BY sort_order
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def search_feeds(self, query):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feeds WHERE name LIKE ? OR url LIKE ? OR tag LIKE ? ORDER BY name",
                (f"%{query}%", f"%{query}%", f"%{query}%"),
            ).fetchall()
        feeds = [dict(r) for r in rows]
        for f in feeds:
            f["tags"] = self.get_feed_tags(f["id"])
        return feeds

    # ── Feed 图标 ──────────────────────────────────────────────
    def set_feed_icon(self, feed_id, data):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET icon=?, favicon_state=2 WHERE id=?", (data or "", feed_id))

    def get_feed_icon(self, feed_id):
        with self._conn() as conn:
            row = conn.execute("SELECT icon FROM feeds WHERE id=?", (feed_id,)).fetchone()
        return (row["icon"] if row else "") or ""

    def feeds_needing_favicon(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT id,name,url FROM feeds WHERE favicon_state=0 AND enabled=1").fetchall()
        return [dict(r) for r in rows]