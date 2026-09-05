"""modules/rss_store slice: OPML import/export.

Spliced from modules/rss_store.py by T13 codebase-reorg.
"""
from pathlib import Path


def export_opml_file(store, file_path):
    opml = store.export_opml()
    Path(file_path).write_text(opml, encoding="utf-8")
    return True


def import_opml_file(store, file_path):
    content = Path(file_path).read_text(encoding="utf-8")
    return store.import_opml(content)
