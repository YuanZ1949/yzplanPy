"""rss_store slice: categories mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from .store_conn import RssStoreBase, _default_category_hex


class CategoriesMixin(RssStoreBase):
    # ── 分类 ──────────────────────────────────────────────────
    def get_categories(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
        return [dict(r) for r in rows]

    def add_category(self, name, color=None):
        if color is None:
            color = _default_category_hex()
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO categories(name,color) VALUES(?,?)", (name, color))

    def remove_category(self, category_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
            conn.execute("DELETE FROM item_categories WHERE category_id=?", (category_id,))

    def update_category(self, category_id, name=None, color=None):
        with self._conn() as conn:
            if name is not None:
                conn.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id))
            if color is not None:
                conn.execute("UPDATE categories SET color=? WHERE id=?", (color, category_id))

    def set_item_category(self, item_hash, category_id):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO item_categories(hash,category_id) VALUES(?,?)",
                (item_hash, category_id),
            )

    def remove_item_category(self, item_hash, category_id):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM item_categories WHERE hash=? AND category_id=?",
                (item_hash, category_id),
            )

    def get_item_categories(self, item_hash):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.color
                FROM categories c
                INNER JOIN item_categories ic ON c.id = ic.category_id
                WHERE ic.hash = ?
                """,
                (item_hash,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_item_feeds(self, item_hash):
        """条目所属的源列表 [{id, name}]（供 mcp_server 等外部层复用）。"""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT f.id, f.name
                FROM feeds f
                JOIN item_feeds if2 ON f.id = if2.feed_id
                WHERE if2.hash = ?
                """,
                (item_hash,),
            ).fetchall()
        return [dict(r) for r in rows]