"""Public financial RSS (pt-BR and en). Empty on timeout — never invent."""
from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

from app.services.context.http import cached_get_text

FEEDS = (
    ("https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419", "pt-BR"),
    ("https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en", "en"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    ("https://feeds.bbci.co.uk/news/business/rss.xml", "en"),
)


def fetch_rss(query: str, *, asset_class: str = "equity_br") -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    feeds = FEEDS
    if asset_class != "crypto":
        feeds = tuple(row for row in FEEDS if row[1] != "crypto")
    for template, lang in feeds:
        url = template.format(q=query.replace(" ", "+"))
        xml = cached_get_text(url, prefix="rss", timeout=4.0, ttl=600)
        if not xml:
            continue
        hits.extend(_parse(xml, lang))
        if len(hits) >= 10:
            break
    return hits[:10]


def _parse(xml: str, lang: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    items = []
    for node in root.iter():
        tag = node.tag.split("}")[-1].lower()
        if tag != "item":
            continue
        title = _child(node, "title")
        link = _child(node, "link") or _child(node, "guid")
        date = _child(node, "pubDate") or _child(node, "published") or ""
        if title and link:
            items.append({
                "titulo": re.sub(r"\s+", " ", title).strip()[:200],
                "url": link.strip(),
                "data": date.strip()[:40],
                "fonte": f"rss:{lang}",
            })
    return items


def _child(node: ET.Element, name: str) -> str | None:
    for child in node:
        if child.tag.split("}")[-1].lower() == name.lower():
            return (child.text or "").strip() or None
    return None
