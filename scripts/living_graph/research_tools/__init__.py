"""Internet research toolchain for Living Graph."""

from .claim_extractor import ClaimExtractionResult, extract_claims_from_page
from .event_stream import emit_event, read_events
from .extractor import ExtractedPage, extract_page_text
from .fetcher import FetchResult, PageFetcher
from .temporal_planner import TimeWindow, build_role_queries, day_windows, extract_year_range, month_windows, should_zoom_window, year_windows
from .search_provider import SearchResult, build_search_provider, search_seed_urls
from .source_registry import load_source_registry_snapshot

__all__ = [
    "ClaimExtractionResult",
    "ExtractedPage",
    "FetchResult",
    "TimeWindow",
    "PageFetcher",
    "SearchResult",
    "build_role_queries",
    "build_search_provider",
    "day_windows",
    "emit_event",
    "extract_claims_from_page",
    "extract_year_range",
    "extract_page_text",
    "load_source_registry_snapshot",
    "month_windows",
    "read_events",
    "search_seed_urls",
    "should_zoom_window",
    "year_windows",
]
