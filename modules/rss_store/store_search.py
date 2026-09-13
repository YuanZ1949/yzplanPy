"""rss_store slice: search / list queries / sidebar data mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from core.perf import trace

from .store_conn import RssStoreBase


class SearchMixin(RssStoreBase):
    # ── 搜索 ──────────────────────────────────────────────────
    @trace()
    def search(self, query, limit=200, offset=0, field=None, date_from=None, date_to=None):
        with self._conn() as conn:
            conditions = []
            params = []
            if field == "title":
                conditions.append("i.title LIKE ?")
                params.append(f"%{query}%")
            elif field == "description":
                conditions.append("i.description LIKE ?")
                params.append(f"%{query}%")
            elif field == "link":
                conditions.append("i.link LIKE ?")
                params.append(f"%{query}%")
            else:
                try:
                    rows = conn.execute(
                        "SELECT rowid FROM items_fts WHERE items_fts MATCH ?",
                        (query,),
                    ).fetchall()
                    if rows:
                        fts_ids = [r["rowid"] for r in rows]
                        placeholders = ",".join("?" * len(fts_ids))
                        conditions.append(f"i.id IN ({placeholders})")
                        params.extend(fts_ids)
                    else:
                        conditions.append("(i.title LIKE ? OR i.description LIKE ?)")
                        params.extend([f"%{query}%", f"%{query}%"])
                except Exception:
                    conditions.append("(i.title LIKE ? OR i.description LIKE ?)")
                    params.extend([f"%{query}%", f"%{query}%"])
            if date_from:
                conditions.append("i.published >= ?")
                params.append(date_from)
            if date_to:
                conditions.append("i.published <= ?")
                params.append(date_to)
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            params.extend([limit, offset])
            rows = conn.execute(
                f"""
                SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                       GROUP_CONCAT(s.tag, ' | ') AS tags,
                       CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                       CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                FROM items i
                LEFT JOIN item_sources s ON i.hash = s.hash
                LEFT JOIN item_read r ON i.hash = r.hash
                LEFT JOIN favorites f ON i.hash = f.hash
                {where}
                GROUP BY i.hash
                ORDER BY i.published DESC, i.id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 列表查询 ──────────────────────────────────────────────
    @trace()
    def recent(self, limit=100, tag_filter=None, category_id=None, favorites_only=False, unread_only=False,
               date_range=None, feed_ids=None, tags=None, keyword=None, torrent_hash=None, agg_id=None):
        with self._conn() as conn:
            conditions = []
            params = []
            if feed_ids:
                # 精确到订阅源：item_feeds 关联
                ph = ",".join("?" * len(feed_ids))
                conditions.append("i.hash IN (SELECT hash FROM item_feeds WHERE feed_id IN (%s))" % ph)
                params.extend(list(feed_ids))
            if tags:
                ph3 = ",".join("?" * len(tags))
                conditions.append("i.hash IN (SELECT hash FROM item_sources WHERE tag IN (%s))" % ph3)
                params.extend(tags)
            if agg_id:
                conditions.append("i.hash IN (SELECT hash FROM aggregation_items WHERE agg_id = ?)")
                params.append(agg_id)
            if torrent_hash:
                conditions.append("i.torrent_hash = ?")
                params.append(torrent_hash)
            if keyword:
                conditions.append("(i.title LIKE ? OR i.description LIKE ?)")
                kw = "%{}%".format(keyword)
                params.append(kw)
                params.append(kw)
            if favorites_only:
                conditions.append("f.hash IS NOT NULL")
            if unread_only:
                conditions.append("r.hash IS NULL")
            if tag_filter == "__磁链__":
                conditions.append("(i.link LIKE '%magnet:%' OR i.link LIKE '%.torrent')")
            elif tag_filter == "__文章__":
                conditions.append("NOT (i.link LIKE '%magnet:%' OR i.link LIKE '%.torrent')")
            elif tag_filter:
                conditions.append("i.hash IN (SELECT hash FROM item_sources WHERE tag = ?)")
                params.append(tag_filter)
            if category_id:
                conditions.append("i.hash IN (SELECT hash FROM item_categories WHERE category_id = ?)")
                params.append(category_id)
            if date_range == "today":
                conditions.append("i.published >= date('now', 'localtime', '-1 day')")
            elif date_range == "week":
                conditions.append("i.published >= date('now', 'localtime', '-7 days')")
            elif date_range == "month":
                conditions.append("i.published >= date('now', 'localtime', '-1 month')")
            elif isinstance(date_range, (tuple, list)) and len(date_range) == 3 and date_range[0] == "range":
                conditions.append("i.published >= ?")
                params.append(date_range[1])
                conditions.append("i.published < date(?, '+1 day')")
                params.append(date_range[2])
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                       GROUP_CONCAT(s.tag, ' | ') AS tags,
                       CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                       CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                FROM items i
                LEFT JOIN item_sources s ON i.hash = s.hash
                LEFT JOIN item_read r ON i.hash = r.hash
                LEFT JOIN favorites f ON i.hash = f.hash
                {where}
                GROUP BY i.hash
                ORDER BY i.published DESC, i.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    @trace()
    def count_items(self, unread_only=False, favorites_only=False, magnet_only=False):
        """侧栏快捷节点计数：全量 / 仅未读 / 仅收藏 / 仅磁链 条数。"""
        with self._conn() as conn:
            conds = []
            if unread_only:
                conds.append("r.hash IS NULL")
            if favorites_only:
                conds.append("f.hash IS NOT NULL")
            if magnet_only:
                conds.append("(i.link LIKE '%magnet:%' OR i.link LIKE '%.torrent')")
            where = (" WHERE " + " AND ".join(conds)) if conds else ""
            row = conn.execute(
                "SELECT COUNT(DISTINCT i.hash) AS n FROM items i "
                "LEFT JOIN item_read r ON i.hash = r.hash "
                "LEFT JOIN favorites f ON i.hash = f.hash" + where
            ).fetchone()
            return int(row["n"] or 0) if row else 0

    # ── 侧边栏 / 聚合节点数据 ──────────────────────────────
    @trace()
    def list_sidebar(self):
        """返回侧边栏所需的节点数据与计数。
        返回 dict: {feeds:[{id,name,tag,group_name,icon,feed_type,enabled,unread,created_at,last_refresh,tags}],
                    aggregations:[{id,name,agg_type,feed_ids,tags,kw_*,created_at,last_refreshed,count,unread}]}"""
        with self._conn() as conn:
            feed_rows = conn.execute(
                "SELECT id,name,tag,group_name,icon,feed_type,enabled,created_at,last_refresh FROM feeds"
            ).fetchall()

            # 一次取所有未读计数（group by feed_id）
            unread_map = {r["feed_id"]: r["c"] for r in conn.execute(
                """SELECT f.feed_id AS feed_id, COUNT(DISTINCT i.hash) AS c
                   FROM items i
                   JOIN item_feeds f ON i.hash=f.hash
                   LEFT JOIN item_read r ON i.hash=r.hash
                   WHERE r.hash IS NULL
                   GROUP BY f.feed_id"""
            ).fetchall()}

            # 一次取所有标签（group by feed_id）
            tags_map = {}
            for r in conn.execute(
                "SELECT feed_id, tag FROM feed_tags ORDER BY feed_id, tag"
            ).fetchall():
                tags_map.setdefault(r["feed_id"], []).append(r["tag"])

            feed_nodes = []
            for f in feed_rows:
                d = dict(f)
                d["unread"] = unread_map.get(f["id"], 0)
                d["tags"] = tags_map.get(f["id"], [])
                feed_nodes.append(d)

            agg_rows = conn.execute(
                "SELECT * FROM aggregations ORDER BY sort_order, created_at"
            ).fetchall()

            agg_count_map = {r["agg_id"]: r["c"] for r in conn.execute(
                "SELECT agg_id, COUNT(*) AS c FROM aggregation_items GROUP BY agg_id"
            ).fetchall()}
            agg_unread_map = {r["agg_id"]: r["c"] for r in conn.execute(
                """SELECT ai.agg_id AS agg_id, COUNT(*) AS c
                   FROM aggregation_items ai
                   LEFT JOIN item_read r ON ai.hash=r.hash
                   WHERE r.hash IS NULL
                   GROUP BY ai.agg_id"""
            ).fetchall()}

            agg_nodes = []
            for a in agg_rows:
                d = dict(a)
                d["count"] = agg_count_map.get(d["id"], 0)
                d["unread"] = agg_unread_map.get(d["id"], 0)
                agg_nodes.append(d)
        return {"feeds": feed_nodes, "aggregations": agg_nodes}

    def get_tags_and_groups(self):
        """全部来源标签与分组名列表（供 mcp_server 等外部层复用）。"""
        with self._conn() as conn:
            tags = [r["tag"] for r in conn.execute(
                "SELECT DISTINCT tag FROM item_sources WHERE tag != '' ORDER BY tag").fetchall()]
            groups = [r["group_name"] for r in conn.execute(
                "SELECT DISTINCT group_name FROM feeds WHERE group_name != '' ORDER BY group_name").fetchall()]
        return {"tags": tags, "groups": groups}