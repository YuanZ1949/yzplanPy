"""rss_store slice: OPML export/import mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
import xml.etree.ElementTree as ET

from .store_conn import RssStoreBase


class OpmlMixin(RssStoreBase):
    # ── OPML ──────────────────────────────────────────────────
    def export_opml(self):
        root = ET.Element("opml", version="2.0")
        head = ET.SubElement(root, "head")
        title = ET.SubElement(head, "title")
        title.text = "YZplan RSS Subscriptions"
        body = ET.SubElement(root, "body")
        groups = {}
        for f in self.list_feeds():
            grp = f.get("group_name", "") or "未分组"
            if grp not in groups:
                groups[grp] = ET.SubElement(body, "outline", text=grp)
            folder = groups[grp]
            attrs = {
                "text": f["name"],
                "title": f["name"],
                "type": "rss",
                "xmlUrl": f["url"],
                "htmlUrl": f["url"],
            }
            if f.get("tag"):
                attrs["description"] = f"标签: {f['tag']}"
            ET.SubElement(folder, "outline", **attrs)
        return ET.tostring(root, encoding="unicode", xml_declaration=True)

    def import_opml(self, opml_content):
        root = ET.fromstring(opml_content)
        count = 0
        for body in root.iter("body"):
            for group_outline in body.findall("outline"):
                group_name = group_outline.get("text", "")
                for outline in group_outline.findall("outline"):
                    xml_url = outline.get("xmlUrl")
                    if xml_url:
                        name = outline.get("text") or outline.get("title") or xml_url
                        tag = ""
                        desc = outline.get("description", "")
                        if desc.startswith("标签: "):
                            tag = desc[4:]
                        self.add_feed(name, xml_url, tag or name, group_name)
                        count += 1
            for outline in body.findall("outline"):
                xml_url = outline.get("xmlUrl")
                if xml_url:
                    name = outline.get("text") or outline.get("title") or xml_url
                    tag = ""
                    desc = outline.get("description", "")
                    if desc.startswith("标签: "):
                        tag = desc[4:]
                    self.add_feed(name, xml_url, tag or name, "")
                    count += 1
        return count