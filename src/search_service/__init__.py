# -*- coding: utf-8 -*-
"""
Search service sub-package (split from the legacy ``src/search_service.py``).

Re-exports every public symbol so existing callers
(``from src.search_service import SearchService`` /
``from src.search_service import SearchResponse, SearchResult`` /
provider class imports / ``get_search_service`` / ``reset_search_service``)
keep working without modification.
"""
from .base_provider import BaseSearchProvider
from .bocha import BochaSearchProvider
from .brave import BraveSearchProvider
from .http_utils import fetch_url_content
from .minimax import MiniMaxSearchProvider
from .models import SearchResponse, SearchResult
from .searxng import SearXNGSearchProvider
from .serpapi import SerpAPISearchProvider
from .service import (
    SearchService,
    get_search_service,
    reset_search_service,
)
from .tavily import TavilySearchProvider

__all__ = [
    "SearchService",
    "SearchResponse",
    "SearchResult",
    "BaseSearchProvider",
    "TavilySearchProvider",
    "SerpAPISearchProvider",
    "BochaSearchProvider",
    "MiniMaxSearchProvider",
    "BraveSearchProvider",
    "SearXNGSearchProvider",
    "fetch_url_content",
    "get_search_service",
    "reset_search_service",
]
