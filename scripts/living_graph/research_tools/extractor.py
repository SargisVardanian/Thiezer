"""HTML/text extraction helpers for research pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import urljoin


@dataclass
class ExtractedPage:
    url: str
    title: str
    text: str
    links: list[str]
    language: str = ""
    markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "links": self.links,
            "language": self.language,
            "markdown": self.markdown,
        }


def _strip_markup(html_text: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html_text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<(br|p|div|li|tr|h1|h2|h3|h4|h5|h6|section|article)\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|tr|h1|h2|h3|h4|h5|h6|section|article)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.I | re.S)
    if match:
        return re.sub(r"\s+", " ", unescape(match.group(1))).strip()
    return ""


def _extract_links(html_text: str, base_url: str) -> list[str]:
    links: list[str] = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.I):
        value = str(href or "").strip()
        if not value or value.startswith("#") or value.startswith("javascript:"):
            continue
        links.append(urljoin(base_url, value))
    seen: set[str] = set()
    deduped: list[str] = []
    for item in links:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:100]


def extract_page_text(body: str, url: str, *, content_type: str = "") -> ExtractedPage:
    title = _extract_title(body)
    text = _strip_markup(body)
    links = _extract_links(body, url) if "<" in body else []
    markdown = text
    if content_type and "html" not in content_type.lower():
        markdown = text
    return ExtractedPage(url=url, title=title, text=text, links=links, markdown=markdown)
