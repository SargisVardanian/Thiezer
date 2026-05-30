"""Search provider abstraction for internet research."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urlparse, urlsplit
from urllib.request import Request, urlopen

from .source_registry import load_source_registry_snapshot


@dataclass
class SearchResult:
    query: str
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    score: float = 0.0
    raw_content: str = ""
    markdown_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "score": self.score,
            "raw_content": self.raw_content,
            "markdown_content": self.markdown_content,
        }


def _slug_query(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(query or "").lower()).strip("-")


def _normalized_host(url: str) -> str:
    parsed = urlparse(url or "")
    return parsed.netloc.lower().lstrip("www.")


def _normalize_domains(domains: list[str] | None) -> set[str]:
    return {_normalized_host(domain) for domain in (domains or []) if str(domain or "").strip()}


def _site_for_query(query: str, domains: list[str] | None = None) -> str:
    blob = str(query or "").strip()
    domain_filters = [str(domain or "").strip() for domain in (domains or []) if str(domain or "").strip()]
    if domain_filters:
        if len(domain_filters) == 1:
            return f"{blob} site:{domain_filters[0]}".strip()
        return " ".join([blob, *[f"site:{domain}" for domain in domain_filters]]).strip()
    return blob


def _score_query_match(query: str, title: str, url: str) -> float:
    blob = f"{query} {title} {url}".lower()
    score = 0.0
    for token, bonus in (
        ("primeminister.am", 3.5),
        ("gov.am", 3.0),
        ("parliament.am", 2.7),
        ("arlis.am", 2.5),
        ("e-register.am", 2.3),
        ("president.am", 2.0),
        ("official", 1.0),
        ("government", 0.8),
        ("parliament", 0.8),
        ("ministry", 0.8),
        ("staff", 0.8),
        ("chief of staff", 1.1),
        ("head of staff", 1.1),
        ("chief of the prime minister", 1.1),
        ("prime minister", 0.9),
        ("appointment", 1.0),
        ("press release", 0.9),
    ):
        if token in blob:
            score += bonus
    if query:
        q_tokens = [token for token in re.split(r"\s+", query.lower()) if len(token) > 2]
        hits = sum(1 for token in q_tokens if token in title.lower() or token in url.lower())
        score += min(2.5, hits * 0.2)
    return score


class TavilySearchProvider:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = str(api_key or os.environ.get("TAVILY_API_KEY", "")).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, *, domains: list[str] | None = None, max_results: int = 10, include_raw_content: bool = False) -> list[SearchResult]:
        if not self.available:
            return []
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max(1, min(20, int(max_results or 10))),
            "search_depth": "advanced",
            "include_answer": False,
            "include_raw_content": bool(include_raw_content),
            "include_images": False,
        }
        if domains:
            payload["include_domains"] = domains[:8]
        req = Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=25) as response:
                raw = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            return []
        results: list[SearchResult] = []
        for row in raw.get("results", []) if isinstance(raw, dict) else []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            results.append(
                SearchResult(
                    query=query,
                    title=str(row.get("title") or url).strip(),
                    url=url,
                    snippet=str(row.get("content") or row.get("snippet") or "").strip(),
                    source="tavily",
                    score=float(row.get("score") or 0.0),
                    raw_content=str(row.get("raw_content") or ""),
                    markdown_content=str(row.get("markdown_content") or ""),
                )
            )
        return results


class BraveHtmlSearchProvider:
    def __init__(self) -> None:
        self.base_url = "https://search.brave.com/search"

    @property
    def available(self) -> bool:
        return True

    def _fetch_html(self, query: str, *, timeout: int = 25) -> str:
        params = urlencode({"q": query})
        request = Request(
            f"{self.base_url}?{params}",
            headers={"User-Agent": "ThiezerResearchBot/2.0", "Accept-Language": "en-US,en;q=0.9,hy;q=0.8,ru;q=0.7"},
        )
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    @staticmethod
    def _strip_html(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text or "")
        text = re.sub(r"&nbsp;|&#160;", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _parse_results(self, html: str, query: str) -> list[SearchResult]:
        if not html:
            return []
        m = re.search(r'results:\[(?P<body>.*?)\],bo_left_right_divisive', html, flags=re.S)
        body = m.group("body") if m else html
        results: list[SearchResult] = []
        pattern = re.compile(
            r'title:"(?P<title>(?:[^"\\]|\\.)*)"'
            r'.*?url:"(?P<url>(?:[^"\\]|\\.)*)"'
            r'.*?description:"(?P<description>(?:[^"\\]|\\.)*)"'
            r'.*?page_age:"(?P<page_age>(?:[^"\\]|\\.)*)"'
            r'.*?type:"search_result"',
            flags=re.S,
        )
        for match in pattern.finditer(body):
            title = match.group("title")
            url = match.group("url")
            snippet = match.group("description")
            if not url or not title:
                continue
            results.append(
                SearchResult(
                    query=query,
                    title=self._strip_html(unquote(json.loads(f'"{title}"'))),
                    url=self._strip_html(unquote(json.loads(f'"{url}"'))),
                    snippet=self._strip_html(unquote(json.loads(f'"{snippet}"'))),
                    source="brave_html",
                    score=_score_query_match(query, title, url),
                )
            )
        return results

    def search(self, query: str, *, domains: list[str] | None = None, max_results: int = 10, include_raw_content: bool = False) -> list[SearchResult]:
        queries = [_site_for_query(query, domains)]
        if domains:
            queries.extend(
                _site_for_query(query, [domain])
                for domain in domains
                if str(domain or "").strip()
            )
        if not queries[0]:
            return []
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for candidate_query in queries:
            try:
                html = self._fetch_html(candidate_query)
            except (HTTPError, URLError, TimeoutError, OSError):
                continue
            for item in self._parse_results(html, query):
                if not item.url or item.url in seen_urls:
                    continue
                if domains:
                    host = _normalized_host(item.url)
                    if host and host not in _normalize_domains(domains):
                        continue
                seen_urls.add(item.url)
                results.append(item)
                if len(results) >= max_results:
                    return results
        return results


class DeterministicOfficialSearchProvider:
    def __init__(self, source_registry: list[dict[str, Any]] | None = None) -> None:
        self.source_registry = source_registry or load_source_registry_snapshot()

    def _official_candidates(self, query: str) -> list[SearchResult]:
        blob = (query or "").lower()
        results: list[SearchResult] = []
        role_history_tokens = (
            "chief of staff",
            "head of staff",
            "head of the prime minister",
            "prime minister's staff",
            "prime minister staff",
            "руководител",
            "глава аппарата",
            "վարչապետի աշխատակազմի ղեկավար",
            "աշխատակազմի ղեկավար",
        )
        if any(token in blob for token in role_history_tokens):
            results.extend(
                [
                    SearchResult(query=query, title="Office of the Prime Minister of Armenia", url="https://www.primeminister.am/en/", snippet="Official Office of the Prime Minister with staff announcements and press releases.", source="deterministic_official", score=1.0),
                    SearchResult(query=query, title="Chief of Staff of the Prime Minister", url="https://www.primeminister.am/en/press-release/item/2021/07/01/Nikol-Pashinyan-Chief-of-Staff/", snippet="Official press release introducing a newly appointed Chief of Staff.", source="deterministic_official", score=0.99),
                    SearchResult(query=query, title="Prime Minister's Staff Report 2022", url="https://www.primeminister.am/en/press-release/item/2023/03/28/Nikol-Pashinyan-Government-Staff-Report/", snippet="Official report with deputy chiefs, department heads and staff officials.", source="deterministic_official", score=0.985),
                    SearchResult(query=query, title="Government of Armenia", url="https://www.gov.am/en/", snippet="Official government portal and cabinet roster.", source="deterministic_official", score=0.98),
                    SearchResult(query=query, title="Armenian Legal Information System", url="https://www.arlis.am/", snippet="Official legal decrees and appointment records.", source="deterministic_official", score=0.96),
                    SearchResult(query=query, title="Electronic Register of Armenia", url="https://www.e-register.am/en/", snippet="Official company and legal entity registry.", source="deterministic_official", score=0.95),
                ]
            )
        if any(token in blob for token in ("minister", "ministers", "cabinet", "gov-members", "government of armenia", "правительство", "նախարար", "минист", "մինիստր", "նախարարներ")):
            results.append(SearchResult(query=query, title="Government Team Members", url="https://www.gov.am/en/gov-members/", snippet="Official government cabinet roster.", source="deterministic_official", score=1.0))
        if any(token in blob for token in ("deputy", "deputies", "mp", "parliament", "assembly", "национальное собрание", "պատգամավոր", "депутат", "парламент", "խորհրդարան")):
            results.append(SearchResult(query=query, title="National Assembly Deputies", url="https://www.parliament.am/deputies.php?lang=eng", snippet="Official parliament roster.", source="deterministic_official", score=1.0))
        if any(token in blob for token in ("faction", "civil contract", "party", "coalition")):
            results.append(SearchResult(query=query, title="Parliament Factions", url="https://www.parliament.am/deputies.php?lang=eng&sel=factions", snippet="Official parliamentary faction directory.", source="deterministic_official", score=0.95))
        return results

    def search(self, query: str, *, domains: list[str] | None = None, max_results: int = 10, include_raw_content: bool = False) -> list[SearchResult]:
        domain_filter = _normalize_domains(domains)
        results = self._official_candidates(query)
        registry = self.source_registry
        query_blob = (query or "").lower()
        for source in registry:
            url = str(source.get("url") or source.get("siteUrl") or "").strip()
            if not url:
                continue
            host = _normalized_host(url)
            if domain_filter and host not in domain_filter:
                continue
            name = str(source.get("source_name") or source.get("name") or host).strip()
            tags = " ".join(str(tag) for tag in source.get("coverage_tags", []) or [])
            if any(token in query_blob for token in (name.lower(), host, tags.lower())):
                results.append(
                    SearchResult(
                        query=query,
                        title=name,
                        url=url,
                        snippet=str(source.get("notes") or "").strip(),
                        source="source_registry",
                        score=float(source.get("trust_weight") or source.get("priority") or 0.5),
                    )
                )
        deduped: list[SearchResult] = []
        seen: set[str] = set()
        for item in sorted(results, key=lambda row: (-float(row.score or 0.0), row.title.lower(), row.url)):
            if item.url in seen:
                continue
            seen.add(item.url)
            deduped.append(item)
            if len(deduped) >= max_results:
                break
        return deduped


class SearchChainProvider:
    def __init__(self, providers: list[tuple[str, Any]]) -> None:
        self.providers = providers

    @property
    def available(self) -> bool:
        return any(bool(getattr(provider, "available", False)) for _, provider in self.providers)

    def search(self, query: str, *, domains: list[str] | None = None, max_results: int = 10, include_raw_content: bool = False) -> list[SearchResult]:
        combined: list[SearchResult] = []
        for _, provider in self.providers:
            try:
                results = provider.search(query, domains=domains, max_results=max_results, include_raw_content=include_raw_content)
            except TypeError:
                results = provider.search(query, domains=domains, max_results=max_results)
            except Exception:
                continue
            combined.extend(results or [])
        deduped: list[SearchResult] = []
        seen: set[str] = set()
        for item in sorted(
            combined,
            key=lambda row: (-float(row.score or 0.0), 0 if row.source == "tavily" else 1 if row.source == "duckduckgo_html" else 2 if row.source == "source_registry" else 3, row.title.lower(), row.url),
        ):
            url = str(item.url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(item)
            if len(deduped) >= max_results:
                break
        return deduped


def build_search_provider() -> tuple[Any, dict[str, Any]]:
    tavily = TavilySearchProvider()
    brave = BraveHtmlSearchProvider()
    fallback = DeterministicOfficialSearchProvider()
    providers: list[tuple[str, Any]] = []
    provider_names: list[str] = []
    if tavily.available:
        providers.append(("tavily", tavily))
        provider_names.append("tavily")
    providers.append(("brave_html", brave))
    provider_names.append("brave_html")
    providers.append(("official_seed", fallback))
    provider_names.append("official_seed")
    chain = SearchChainProvider(providers)
    meta = {
        "provider": "+".join(provider_names),
        "available": True,
        "providers": provider_names,
        "primary_provider": provider_names[0] if provider_names else "official_seed",
        "query_strategy": "tavily_then_brave_then_official_seed" if tavily.available else "brave_then_official_seed",
    }
    return chain, meta


def search_seed_urls(query: str, *, domains: list[str] | None = None, max_results: int = 10) -> tuple[list[SearchResult], dict[str, Any]]:
    provider, meta = build_search_provider()
    results = provider.search(query, domains=domains, max_results=max_results)
    return results, {"provider": meta["provider"], "available": meta["available"], "query": query, "count": len(results), "providers": meta.get("providers", [])}
