"""rss_store slice: filter rules mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
import re

from .store_conn import RssStoreBase


class FilterRulesMixin(RssStoreBase):
    # ── 过滤规则 ──────────────────────────────────────────────
    def get_filter_rules(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM filter_rules ORDER BY sort_order, id").fetchall()
        return [dict(r) for r in rows]

    def add_filter_rule(self, name, field, operator, value, action, action_value=""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO filter_rules(name,field,operator,value,action,action_value) VALUES(?,?,?,?,?,?)",
                (name, field, operator, value, action, action_value),
            )

    def remove_filter_rule(self, rule_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM filter_rules WHERE id=?", (rule_id,))

    def update_filter_rule(self, rule_id, enabled=None):
        with self._conn() as conn:
            if enabled is not None:
                conn.execute("UPDATE filter_rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))

    def add_filter_rule_full(self, name, field, operator, value, action, action_value="", enabled=1):
        """完整建过滤规则（含 enabled），返回新行 id（供 mcp_server 等外部层复用）。"""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO filter_rules(name,field,operator,value,action,action_value,enabled) "
                "VALUES(?,?,?,?,?,?,?)",
                (name, field, operator, value, action, action_value, 1 if enabled else 0))
            return cur.lastrowid

    def update_filter_rule_full(self, rule_id, **kwargs):
        """按字段更新过滤规则（enabled 做 int 强转），供 mcp_server 等外部层复用。"""
        allowed = ("name", "field", "operator", "value", "action", "action_value", "enabled")
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [rule_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE filter_rules SET {sets} WHERE id=?", vals)

    def apply_filter_rules(self, entries):
        rules = self.get_filter_rules()
        for entry in entries:
            for rule in rules:
                if not rule["enabled"]:
                    continue
                field_val = entry.get(rule["field"], "")
                match = False
                if rule["operator"] == "contains":
                    match = rule["value"].lower() in field_val.lower()
                elif rule["operator"] == "not_contains":
                    match = rule["value"].lower() not in field_val.lower()
                elif rule["operator"] == "equals":
                    match = rule["value"].lower() == field_val.lower()
                elif rule["operator"] == "starts_with":
                    match = field_val.lower().startswith(rule["value"].lower())
                elif rule["operator"] == "ends_with":
                    match = field_val.lower().endswith(rule["value"].lower())
                elif rule["operator"] == "regex":
                    try:
                        match = bool(re.search(rule["value"], field_val, re.IGNORECASE))
                    except re.error:
                        pass
                if match:
                    if rule["action"] == "tag":
                        entry["extra_tag"] = rule["action_value"]
                    elif rule["action"] == "skip":
                        entry["_skip"] = True
                    elif rule["action"] == "highlight":
                        entry["_highlight"] = True
        return entries