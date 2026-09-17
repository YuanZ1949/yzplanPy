"""rss_store slice: aggregation mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
import json

from .store_conn import (
    RssStoreBase,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_SIMILARITY_GRANULARITY,
    MAX_SIMILARITY_GRANULARITY,
)


def _load_list(v):
    """兼容 JSON 字符串与原生 list 两种存储形态（str→json.loads，list 直接用）。"""
    if isinstance(v, str):
        return json.loads(v or "[]")
    return list(v or [])


def _clamp_granularity(v):
    """钳制 n-gram 粒度到 [1, MAX_SIMILARITY_GRANULARITY]；非法值回退默认 1。"""
    try:
        g = int(v)
    except (TypeError, ValueError):
        return DEFAULT_SIMILARITY_GRANULARITY
    return max(DEFAULT_SIMILARITY_GRANULARITY, min(g, MAX_SIMILARITY_GRANULARITY))


class AggregationMixin(RssStoreBase):
    # ── 聚合（手动，独立快照） ──────────────────────────────
    def list_aggregations(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM aggregations ORDER BY sort_order, created_at").fetchall()
        return [dict(r) for r in rows]

    def get_aggregation_item_count(self, agg_id):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM aggregation_items WHERE agg_id=?", (agg_id,)).fetchone()
        return row["c"] if row else 0

    def get_aggregation(self, agg_id):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM aggregations WHERE id=?", (agg_id,)).fetchone()
        return dict(row) if row else None

    def add_aggregation(self, name, agg_type="mixed", feed_ids=None, tags=None,
                        kw_required=None, kw_optional=None, kw_forbidden=None, sort_order=0,
                        parent_id=0, similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD,
                        similarity_granularity=DEFAULT_SIMILARITY_GRANULARITY):
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO aggregations(name,agg_type,feed_ids,tags,kw_required,kw_optional,kw_forbidden,sort_order,parent_id,similarity_threshold,similarity_granularity)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (name, agg_type,
                 json.dumps(feed_ids or []), json.dumps(tags or []),
                 json.dumps(kw_required or []), json.dumps(kw_optional or []), json.dumps(kw_forbidden or []),
                 sort_order, int(parent_id), float(similarity_threshold),
                 _clamp_granularity(similarity_granularity)),
            )
            return cur.lastrowid

    def sibling_aggregation_ids(self, parent_id, exclude_id):
        """同一父聚合下、除 exclude_id 外的所有子聚合 id（含 remainder 自身）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM aggregations WHERE parent_id = ? AND id != ? ORDER BY id",
                (int(parent_id), int(exclude_id)),
            ).fetchall()
        return [r[0] for r in rows]

    def update_aggregation(self, agg_id, **kwargs):
        allowed = {"name", "agg_type", "feed_ids", "tags", "kw_required", "kw_optional", "kw_forbidden",
                   "sort_order", "enabled", "parent_id", "similarity_threshold", "similarity_granularity"}
        for k in ("feed_ids", "tags", "kw_required", "kw_optional", "kw_forbidden"):
            if k in kwargs and not isinstance(kwargs[k], str) and kwargs[k] is not None:
                kwargs[k] = json.dumps(kwargs[k])
        if "similarity_granularity" in kwargs:
            kwargs["similarity_granularity"] = _clamp_granularity(kwargs["similarity_granularity"])
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [agg_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE aggregations SET {sets} WHERE id=?", vals)

    def remove_aggregation(self, agg_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM aggregation_items WHERE agg_id IN (SELECT id FROM aggregations WHERE parent_id=?)", (agg_id,))
            conn.execute("DELETE FROM aggregations WHERE parent_id=?", (agg_id,))
            conn.execute("DELETE FROM aggregation_items WHERE agg_id=?", (agg_id,))
            conn.execute("DELETE FROM aggregations WHERE id=?", (agg_id,))

    @staticmethod
    def _keyword_clauses(agg):
        """按三桶关键词生成 SQL 条件（AND 关系）。
        必须(required)：每个命中 title|desc；可选(optional)：至少一个（OR，空=不限）；
        禁止(forbidden)：每个都不得命中。返回 (conditions, params)。"""
        conditions = []
        params = []
        req = _load_list(agg.get("kw_required"))
        opt = _load_list(agg.get("kw_optional"))
        forb = _load_list(agg.get("kw_forbidden"))
        for k in req:
            p = "%{}%".format(k)
            conditions.append("(i.title LIKE ? OR i.description LIKE ?)")
            params.extend([p, p])
        if opt:
            parts = []
            for k in opt:
                p = "%{}%".format(k)
                parts.append("(i.title LIKE ? OR i.description LIKE ?)")
                params.extend([p, p])
            conditions.append("(" + " OR ".join(parts) + ")")
        for k in forb:
            p = "%{}%".format(k)
            conditions.append("NOT (i.title LIKE ? OR i.description LIKE ?)")
            params.extend([p, p])
        return conditions, params

    def refresh_aggregation(self, agg_id):
        """重建聚合快照：取成员(订阅源/标签)的已入库条目 → 按类型过滤 → 写入 aggregation_items。"""
        agg = self.get_aggregation(agg_id)
        if not agg or not agg.get("enabled"):
            return 0
        agg_type = agg.get("agg_type") or "mixed"
        parent_id = int(agg.get("parent_id") or 0)
        scope = []
        params = []
        if parent_id > 0:
            # 子聚合：从父快照中筛选，跳过 feed_ids/tags scope
            scope.append("i.hash IN (SELECT hash FROM aggregation_items WHERE agg_id=?)")
            params.append(parent_id)
        else:
            feed_ids = json.loads(agg.get("feed_ids") or "[]")
            tags = json.loads(agg.get("tags") or "[]")
            if feed_ids:
                ph = ",".join("?" * len(feed_ids))
                scope.append("i.hash IN (SELECT hash FROM item_feeds WHERE feed_id IN (%s))" % ph)
                params.extend(feed_ids)
            if tags:
                ph2 = ",".join("?" * len(tags))
                scope.append("i.hash IN (SELECT hash FROM item_sources WHERE tag IN (%s))" % ph2)
                params.extend(tags)
        if agg_type == "torrent":
            scope.append("(i.torrent_hash != '' OR i.link LIKE '%magnet:%' OR i.link LIKE '%.torrent')")
        elif agg_type == "keyword":
            kc, kp = self._keyword_clauses(agg)
            scope.extend(kc)
            params.extend(kp)
        elif agg_type == "remainder":
            # 精确补集：父快照 − 兄弟子聚合成员（hash 并集 + torrent_hash 并集，空 BTIH 豁免）
            sib = self.sibling_aggregation_ids(parent_id, agg_id)
            if sib:
                ph = ",".join("?" * len(sib))
                scope.append("i.hash NOT IN (SELECT hash FROM aggregation_items WHERE agg_id IN (%s))" % ph)
                params.extend(sib)
                scope.append("(i.torrent_hash = '' OR i.torrent_hash IS NULL OR i.torrent_hash NOT IN (SELECT i2.torrent_hash FROM items i2 JOIN aggregation_items ai ON ai.hash = i2.hash WHERE ai.agg_id IN (%s) AND i2.torrent_hash != ''))" % ph)
                params.extend(sib)
        with self._conn() as conn:
            if not scope:
                conn.execute("DELETE FROM aggregation_items WHERE agg_id=?", (agg_id,))
                conn.execute("UPDATE aggregations SET last_refreshed=datetime('now','localtime') WHERE id=?", (agg_id,))
                return 0
            where = " AND ".join(scope)
            rows = conn.execute(f"SELECT DISTINCT i.hash AS hash FROM items i WHERE {where}", params).fetchall()
            conn.execute("DELETE FROM aggregation_items WHERE agg_id=?", (agg_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO aggregation_items(agg_id, hash) VALUES(?,?)",
                [(agg_id, r["hash"]) for r in rows],
            )
            conn.execute("UPDATE aggregations SET last_refreshed=datetime('now','localtime') WHERE id=?", (agg_id,))
        return len(rows)

    def aggregation_titles(self, agg_id, limit=200):
        """返回聚合快照中条目的标题列表（按添加时间降序）。

        limit 为 None / 0 时返回全部。注意：SQLite 的 LIMIT 不接受绑定为 NULL 的
        参数（sqlite3.IntegrityError: datatype mismatch），故不能无条件拼接 "LIMIT ?"。
        agg_id 强转 int（非整数回退 0），<=0 早退返回 []（未持久化的新聚合）。
        """
        try:
            agg_id = int(agg_id)
        except (TypeError, ValueError):
            agg_id = 0
        if agg_id <= 0:
            return []
        sql = (
            "SELECT i.title FROM aggregation_items a "
            "INNER JOIN items i ON i.hash=a.hash "
            "WHERE a.agg_id=? ORDER BY a.added_at DESC"
        )
        with self._conn() as conn:
            if limit:
                rows = conn.execute(sql + " LIMIT ?", (agg_id, limit)).fetchall()
            else:
                rows = conn.execute(sql, (agg_id,)).fetchall()
        return [r["title"] for r in rows]

    def count_aggregation_hits(self, agg):
        """按聚合条件统计命中条数（S1 命中预览，不写入快照）。"""
        agg_type = agg.get("agg_type") or "mixed"
        parent_id = int(agg.get("parent_id") or 0)
        scope = []
        params = []
        # ── scope 构建（与 refresh_aggregation 对齐） ──
        if parent_id > 0:
            scope.append("i.hash IN (SELECT hash FROM aggregation_items WHERE agg_id=?)")
            params.append(parent_id)
        else:
            feed_ids = _load_list(agg.get("feed_ids"))
            tags = _load_list(agg.get("tags"))
            if feed_ids:
                ph = ",".join("?" * len(feed_ids))
                scope.append("i.hash IN (SELECT hash FROM item_feeds WHERE feed_id IN (%s))" % ph)
                params.extend(feed_ids)
            if tags:
                ph2 = ",".join("?" * len(tags))
                scope.append("i.hash IN (SELECT hash FROM item_sources WHERE tag IN (%s))" % ph2)
                params.extend(tags)
        # ── type 过滤 ──
        if agg_type == "torrent":
            scope.append("(i.torrent_hash != '' OR i.link LIKE '%magnet:%' OR i.link LIKE '%.torrent')")
        elif agg_type == "keyword":
            kc, kp = self._keyword_clauses(agg)
            scope.extend(kc)
            params.extend(kp)
        elif agg_type == "remainder":
            sib = self.sibling_aggregation_ids(parent_id, agg["id"])
            if sib:
                ph = ",".join("?" * len(sib))
                scope.append("i.hash NOT IN (SELECT hash FROM aggregation_items WHERE agg_id IN (%s))" % ph)
                params.extend(sib)
        # ── 查询 ──
        if not scope:
            return 0
        where = " AND ".join(scope)
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM items i WHERE {where}", params
            ).fetchone()
        return row["c"] if row else 0

    def get_aggregation_torrent_groups(self, agg_id, limit=200):
        """磁链hash类型聚合：按 torrent_hash 分组，供方案B 折叠/展开渲染。"""
        with self._conn() as conn:
            sql = """
                SELECT i.torrent_hash AS hash,
                       COUNT(DISTINCT i.hash) AS count,
                       COUNT(DISTINCT fi.feed_id) AS feed_count,
                       (SELECT i2.title FROM items i2 WHERE i2.torrent_hash=i.torrent_hash ORDER BY i2.id DESC LIMIT 1) AS title
                FROM aggregation_items ai
                JOIN items i ON i.hash=ai.hash
                LEFT JOIN item_feeds fi ON fi.hash=i.hash
                WHERE ai.agg_id=?
                GROUP BY i.torrent_hash
                ORDER BY MAX(i.published) DESC, COUNT(DISTINCT i.hash) DESC
                """
            if limit:
                sql += " LIMIT ?"
                rows = conn.execute(sql, (agg_id, limit)).fetchall()
            else:
                rows = conn.execute(sql, (agg_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_torrent_groups(self, agg_id, limit=200):
        """聚合成员按条目 hash 分组（每条目出现的源数 + 首条标题），供 mcp_server 等外部层复用。

        limit 为 None / 0 时返回全部（同 aggregation_titles）。
        """
        sql = (
            "SELECT ai.hash, COUNT(*) AS feed_count, MIN(i.title) AS title "
            "FROM aggregation_items ai JOIN items i ON i.hash=ai.hash "
            "WHERE ai.agg_id=? GROUP BY ai.hash ORDER BY feed_count DESC"
        )
        with self._conn() as conn:
            if limit:
                rows = conn.execute(sql + " LIMIT ?", (agg_id, limit)).fetchall()
            else:
                rows = conn.execute(sql, (agg_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_aggregation_torrent_items(self, agg_id, torrent_hash):
        """磁链hash类型聚合：某分组(hash)内的成员条目（回退全文）。"""
        with self._conn() as conn:
            if torrent_hash:
                rows = conn.execute(
                    """SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                              GROUP_CONCAT(s.tag, ' | ') AS tags,
                              CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                              CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                       FROM aggregation_items ai
                       JOIN items i ON i.hash=ai.hash
                       LEFT JOIN item_sources s ON i.hash=s.hash
                       LEFT JOIN item_read r ON i.hash=r.hash
                       LEFT JOIN favorites f ON i.hash=f.hash
                       WHERE ai.agg_id=? AND i.torrent_hash=?
                       GROUP BY i.hash ORDER BY i.published DESC, i.id DESC""",
                    (agg_id, torrent_hash),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                              GROUP_CONCAT(s.tag, ' | ') AS tags,
                              CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                              CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                       FROM aggregation_items ai
                       JOIN items i ON i.hash=ai.hash
                       LEFT JOIN item_sources s ON i.hash=s.hash
                       LEFT JOIN item_read r ON i.hash=r.hash
                       LEFT JOIN favorites f ON i.hash=f.hash
                       WHERE ai.agg_id=? AND (i.torrent_hash='' OR i.torrent_hash IS NULL)
                       GROUP BY i.hash ORDER BY i.published DESC, i.id DESC""",
                    (agg_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_all_aggregation_torrent_items(self, agg_id):
        """一次查询获取整个聚合的所有成员条目，按 torrent_hash 分组返回 {hash: [items]}。"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                          GROUP_CONCAT(s.tag, ' | ') AS tags,
                          CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                          CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                   FROM aggregation_items ai
                   JOIN items i ON i.hash=ai.hash
                   LEFT JOIN item_sources s ON i.hash=s.hash
                   LEFT JOIN item_read r ON i.hash=r.hash
                   LEFT JOIN favorites f ON i.hash=f.hash
                   WHERE ai.agg_id=?
                   GROUP BY i.hash ORDER BY i.torrent_hash, i.published DESC, i.id DESC""",
                (agg_id,),
            ).fetchall()
        grouped = {}
        for r in rows:
            d = dict(r)
            th = d.get("torrent_hash") or ""
            grouped.setdefault(th, []).append(d)
        return grouped

    def get_torrent_group_items(self, torrent_hash, limit=500):
        return self.recent(limit=limit, torrent_hash=torrent_hash, tag_filter=None)