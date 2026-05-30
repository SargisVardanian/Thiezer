"""Page fetcher for internet research."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    body: str
    error: str = ""
    fetched_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "body": self.body,
            "error": self.error,
            "fetched_at": self.fetched_at,
        }


class PageFetcher:
    def fetch(self, url: str, *, timeout: int = 20) -> FetchResult:
        request = Request(url, headers={"User-Agent": "ThiezerResearchBot/2.0", "Accept-Language": "hy,en,ru;q=0.8"})
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                content_type = str(response.headers.get("Content-Type", "")).strip()
                final_url = getattr(response, "url", url) or url
                status_code = int(getattr(response, "status", 200) or 200)
        except HTTPError as exc:
            return FetchResult(url=url, final_url=url, status_code=int(exc.code or 0), content_type="", body="", error=f"http_error:{exc.code}:{exc.reason}")
        except URLError as exc:
            return FetchResult(url=url, final_url=url, status_code=0, content_type="", body="", error=f"url_error:{exc.reason}")
        except Exception as exc:
            return FetchResult(url=url, final_url=url, status_code=0, content_type="", body="", error=f"fetch_error:{exc}")
        if "text" in content_type or "html" in content_type or not content_type:
            body = raw.decode("utf-8", errors="replace")
        else:
            body = unescape(raw.decode("utf-8", errors="replace"))
        return FetchResult(url=url, final_url=final_url, status_code=status_code, content_type=content_type, body=body)
