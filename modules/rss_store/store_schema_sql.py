"""rss_store slice: schema DDL (CREATE TABLE script with color placeholders).

Spliced from modules/rss_store/store.py by store-split refactor.
@CATEGORY_COLOR@ / @KEYWORD_COLOR@ 占位符在 _init_schema() 调用时替换，
保证主题令牌延迟解析（模块级不依赖 Qt）。
"""

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS feeds(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    tag TEXT,
    enabled INTEGER DEFAULT 1,
    group_name TEXT DEFAULT '',
    refresh_interval INTEGER DEFAULT 21600,
    last_refresh TEXT,
    custom_headers TEXT DEFAULT '{}',
    etag TEXT DEFAULT '',
    last_modified TEXT DEFAULT '',
    last_error TEXT DEFAULT '',
    error_count INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,
    title TEXT,
    link TEXT,
    published TEXT,
    description TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    read_time INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS item_sources(
    hash TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY(hash, tag)
);
CREATE TABLE IF NOT EXISTS item_read(
    hash TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS read_history(
    hash TEXT PRIMARY KEY,
    read_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS favorites(
    hash TEXT PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    color TEXT DEFAULT '@CATEGORY_COLOR@',
    sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS item_categories(
    hash TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    PRIMARY KEY(hash, category_id)
);
CREATE TABLE IF NOT EXISTS filter_rules(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    field TEXT DEFAULT 'title',
    operator TEXT DEFAULT 'contains',
    value TEXT NOT NULL,
    action TEXT DEFAULT 'tag',
    action_value TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS keywords(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT UNIQUE NOT NULL,
    color TEXT DEFAULT '@KEYWORD_COLOR@',
    notify INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS item_related(
    hash1 TEXT NOT NULL,
    hash2 TEXT NOT NULL,
    similarity REAL DEFAULT 0.0,
    PRIMARY KEY(hash1, hash2)
);
"""