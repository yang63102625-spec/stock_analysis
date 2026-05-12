# -*- coding: utf-8 -*-
"""Storage sub-package (split from the legacy ``src/storage.py`` single file).

Re-exports every public symbol so existing callers (``from src.storage import
DatabaseManager``, ``from src.storage import get_db``, ORM model imports, etc.)
keep working without modification.
"""
from .manager import DatabaseManager, get_db, persist_llm_usage
from .models import (
    AnalysisHistory,
    Base,
    BacktestResult,
    BacktestSummary,
    ConversationMessage,
    LLMUsage,
    NewsIntel,
    PickerBacktestHistory,
    PickerHistory,
    StockDaily,
)

__all__ = [
    # Manager + module-level helpers
    "DatabaseManager",
    "get_db",
    "persist_llm_usage",
    # ORM base + models
    "Base",
    "StockDaily",
    "NewsIntel",
    "AnalysisHistory",
    "PickerHistory",
    "PickerBacktestHistory",
    "BacktestResult",
    "BacktestSummary",
    "ConversationMessage",
    "LLMUsage",
]
