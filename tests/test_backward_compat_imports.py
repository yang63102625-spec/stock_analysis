# -*- coding: utf-8 -*-
"""Public-import smoke test.

Asserts that the canonical public symbols stay importable after the
sub-package refactors. Legacy shim paths have been removed; this test now
only covers the surviving canonical locations.
"""

from __future__ import annotations

import importlib

import pytest


# (module_path, attribute) pairs that *must* keep working.
LEGACY_SYMBOLS = [
    # src.config package
    ("src.config", "Config"),
    ("src.config", "get_config"),
    ("src.config", "setup_env"),
    ("src.config", "get_api_keys_for_model"),
    ("src.config", "extra_litellm_params"),
    ("src.config", "ConfigIssue"),
    # src.notification_service package
    ("src.notification_service", "NotificationService"),
    ("src.notification_service", "NotificationChannel"),
    ("src.notification_service", "NotificationBuilder"),
    ("src.notification_service", "ChannelDetector"),
    # src.notification_service.formatters
    ("src.notification_service.formatters", "format_feishu_markdown"),
    ("src.notification_service.formatters", "chunk_content_by_max_bytes"),
    ("src.notification_service.formatters", "markdown_to_html_document"),
    # src.notification_service.wechat_formatter
    ("src.notification_service.wechat_formatter", "WechatFormatter"),
    ("src.notification_service.wechat_formatter", "PublishPlatform"),
    # picker package
    ("src.services.picker", "StockPickerService"),
    ("src.services.picker", "StockScreener"),
    ("src.services.picker", "PickerResult"),
    ("src.services.picker", "create_screener_from_config"),
    ("src.services.picker.screener", "StockScreener"),
    # data_provider public surface
    ("data_provider.base", "BaseFetcher"),
    ("data_provider.base", "DataFetcherManager"),
    # Tushare canonical sub-package
    ("data_provider.tushare", "TushareFetcher"),
    ("data_provider.tushare.utils", "_is_etf_code"),
    ("data_provider.tushare.utils", "_is_us_code"),
    ("data_provider.tushare.realtime", "_realtime_list_cache"),
    ("data_provider.tushare.realtime", "_rt_k_cache"),
    # Akshare canonical sub-package
    ("data_provider.akshare", "AkshareFetcher"),
    ("data_provider.akshare", "is_hk_stock_code"),
    ("data_provider.akshare.utils", "SINA_REALTIME_ENDPOINT"),
    ("data_provider.akshare.utils", "TENCENT_REALTIME_ENDPOINT"),
    ("data_provider.akshare.utils", "_to_sina_tx_symbol"),
    ("data_provider.akshare.utils", "_is_hk_code"),
    ("data_provider.akshare.utils", "_is_us_code"),
    # Other fetchers
    ("data_provider.efinance", "EfinanceFetcher"),
    ("data_provider.baostock_fetcher", "BaostockFetcher"),
    ("data_provider.yfinance_fetcher", "YfinanceFetcher"),
    ("data_provider.pytdx_fetcher", "PytdxFetcher"),
    ("data_provider.rate_limit_mixin", "RateLimitMixin"),
    ("data_provider.caching_manager", "CachingDataFetcherManager"),
    ("data_provider.caching_manager", "TTLCache"),
    ("data_provider.caching_manager", "trading_session_ttl"),
    # search_service subpackage
    ("src.search_service", "SearchService"),
    ("src.search_service", "SearchResponse"),
    ("src.search_service", "SearchResult"),
    ("src.search_service", "BaseSearchProvider"),
    ("src.search_service", "TavilySearchProvider"),
    ("src.search_service", "SerpAPISearchProvider"),
    ("src.search_service", "BochaSearchProvider"),
    ("src.search_service", "MiniMaxSearchProvider"),
    ("src.search_service", "BraveSearchProvider"),
    ("src.search_service", "SearXNGSearchProvider"),
    ("src.search_service", "fetch_url_content"),
    ("src.search_service", "get_search_service"),
    ("src.search_service", "reset_search_service"),
    # storage subpackage
    ("src.storage", "DatabaseManager"),
    ("src.storage", "get_db"),
    ("src.storage", "persist_llm_usage"),
    ("src.storage", "Base"),
    ("src.storage", "StockDaily"),
    ("src.storage", "NewsIntel"),
    ("src.storage", "AnalysisHistory"),
    ("src.storage", "PickerHistory"),
    ("src.storage", "PickerBacktestHistory"),
    ("src.storage", "BacktestResult"),
    ("src.storage", "BacktestSummary"),
    ("src.storage", "ConversationMessage"),
    ("src.storage", "LLMUsage"),
    # Unified exceptions
    ("src.exceptions", "RateLimitError"),
    ("src.exceptions", "NetworkError"),
    ("src.exceptions", "DataSourceUnavailableError"),
    ("src.exceptions", "ValidationError"),
    ("src.exceptions", "UnknownError"),
]


@pytest.mark.parametrize("module_path,attr", LEGACY_SYMBOLS)
def test_canonical_symbol_importable(module_path: str, attr: str) -> None:
    module = importlib.import_module(module_path)
    assert hasattr(module, attr), (
        f"Public symbol {module_path}.{attr} no longer importable."
    )


def test_ratelimit_mixin_thread_safe_attrs() -> None:
    """Smoke test: instance-level ``_last_request_time`` is per-instance."""
    from data_provider.rate_limit_mixin import RateLimitMixin

    a = RateLimitMixin()
    b = RateLimitMixin()
    a.__dict__["_last_request_time"] = 1.0
    assert b.__dict__.get("_last_request_time") is None


def test_classify_exception_taxonomy() -> None:
    """``BaseFetcher._classify_exception`` maps to the unified taxonomy."""
    from data_provider.base import BaseFetcher
    from src.exceptions import (
        DataSourceUnavailableError,
        NetworkError,
        RateLimitError,
        UnknownError,
        ValidationError,
    )

    class _Stub(BaseFetcher):  # noqa: D401  -- test stub
        def _fetch_raw_data(self, *a, **kw):  # type: ignore[override]
            raise NotImplementedError

        def _normalize_data(self, *a, **kw):  # type: ignore[override]
            raise NotImplementedError

    f = _Stub()
    assert f._classify_exception(Exception("rate limit exceeded")) is RateLimitError
    assert f._classify_exception(Exception("connection refused")) is NetworkError
    assert f._classify_exception(Exception("HTTP 404 not found")) is DataSourceUnavailableError
    assert f._classify_exception(ValueError("bad")) is ValidationError
    assert f._classify_exception(Exception("???")) is UnknownError
