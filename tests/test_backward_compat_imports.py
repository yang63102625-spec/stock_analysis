# -*- coding: utf-8 -*-
"""Backward-compat smoke test for legacy import paths.

Several refactors moved real implementations behind sub-packages while
keeping shim modules at the original paths. This test asserts every legacy
symbol still imports — preventing accidental shim breakage.

Add new entries here whenever an existing public path is shimmed.
"""

from __future__ import annotations

import importlib

import pytest


# (module_path, attribute) pairs that *must* keep working.
LEGACY_SYMBOLS = [
    # src.config shim
    ("src.config", "Config"),
    ("src.config", "get_config"),
    ("src.config", "setup_env"),
    ("src.config", "get_api_keys_for_model"),
    ("src.config", "extra_litellm_params"),
    ("src.config", "ConfigIssue"),
    # src.notification shim
    ("src.notification", "NotificationService"),
    ("src.notification", "NotificationChannel"),
    ("src.notification", "NotificationBuilder"),
    ("src.notification", "ChannelDetector"),
    # src.formatters shim (still used by mail/wechat/feishu senders)
    ("src.formatters", "format_feishu_markdown"),
    ("src.formatters", "chunk_content_by_max_bytes"),
    ("src.formatters", "markdown_to_html_document"),
    # src.wechat_formatter shim
    ("src.wechat_formatter", "WechatFormatter"),
    ("src.wechat_formatter", "PublishPlatform"),
    # picker shim
    ("src.services.stock_picker_service", "StockPickerService"),
    ("src.services.stock_picker_service", "StockScreener"),
    ("src.services.stock_picker_service", "PickerResult"),
    ("src.services.stock_picker_service", "create_screener_from_config"),
    # data_provider public surface
    ("data_provider.base", "BaseFetcher"),
    ("data_provider.base", "DataFetcherManager"),
    ("data_provider.base", "DataFetchError"),
    ("data_provider.base", "RateLimitError"),
    ("data_provider.base", "DataSourceUnavailableError"),
    ("data_provider.tushare_fetcher", "TushareFetcher"),
    # Tushare shim must keep re-exporting module-level cache state used by
    # callers (quantitative_filter forces realtime cache expiry through it).
    ("data_provider.tushare_fetcher", "_realtime_list_cache"),
    ("data_provider.tushare_fetcher", "_rt_k_cache_time"),
    ("data_provider.tushare_fetcher", "_is_etf_code"),
    ("data_provider.tushare_fetcher", "_is_us_code"),
    # Tushare new sub-package
    ("data_provider.tushare", "TushareFetcher"),
    ("data_provider.akshare_fetcher", "AkshareFetcher"),
    ("data_provider.akshare_fetcher", "SINA_REALTIME_ENDPOINT"),
    ("data_provider.akshare_fetcher", "TENCENT_REALTIME_ENDPOINT"),
    ("data_provider.akshare_fetcher", "_to_sina_tx_symbol"),
    ("data_provider.akshare_fetcher", "_is_hk_code"),
    ("data_provider.akshare_fetcher", "_is_us_code"),
    # Akshare new sub-package
    ("data_provider.akshare", "AkshareFetcher"),
    ("data_provider.akshare", "is_hk_stock_code"),
    ("data_provider.efinance_fetcher", "EfinanceFetcher"),
    ("data_provider.baostock_fetcher", "BaostockFetcher"),
    ("data_provider.yfinance_fetcher", "YfinanceFetcher"),
    ("data_provider.pytdx_fetcher", "PytdxFetcher"),
    ("data_provider.rate_limit_mixin", "RateLimitMixin"),
    ("data_provider.caching_manager", "CachingDataFetcherManager"),
    ("data_provider.caching_manager", "TTLCache"),
    ("data_provider.caching_manager", "trading_session_ttl"),
    # storage subpackage (replaced legacy src/storage.py)
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
    # New unified exceptions
    ("src.exceptions", "RateLimitError"),
    ("src.exceptions", "NetworkError"),
    ("src.exceptions", "DataSourceUnavailableError"),
    ("src.exceptions", "ValidationError"),
    ("src.exceptions", "UnknownError"),
]


@pytest.mark.parametrize("module_path,attr", LEGACY_SYMBOLS)
def test_legacy_symbol_importable(module_path: str, attr: str) -> None:
    module = importlib.import_module(module_path)
    assert hasattr(module, attr), (
        f"Legacy symbol {module_path}.{attr} no longer importable — "
        "check the corresponding compat shim."
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

    # Build a minimal concrete BaseFetcher for testing.
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
