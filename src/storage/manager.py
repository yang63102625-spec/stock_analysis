# -*- coding: utf-8 -*-
"""
``DatabaseManager`` - composes the storage mixins on top of
``_DatabaseManagerCore``. Each concern (daily / news / analysis / picker /
conversation / llm_usage) lives in its own module of this sub-package.
"""
from __future__ import annotations

import logging

from .analysis import _AnalysisMixin
from .conversation import _ConversationMixin
from .daily_data import _DailyDataMixin
from .llm_usage import _LlmUsageMixin
from .manager_base import _DatabaseManagerCore
from .news import _NewsMixin
from .picker import _PickerMixin

logger = logging.getLogger(__name__)


class DatabaseManager(
    _DailyDataMixin,
    _NewsMixin,
    _AnalysisMixin,
    _PickerMixin,
    _ConversationMixin,
    _LlmUsageMixin,
    _DatabaseManagerCore,
):
    """Singleton database manager.

    See ``src.storage`` for the split modules. The class body is intentionally
    empty - all behaviour comes from the mixins.
    """

    __doc__ += "\n\nSee ``src.storage`` package for the split modules."


def get_db() -> DatabaseManager:
    """Convenience accessor for the shared ``DatabaseManager`` singleton."""
    return DatabaseManager.get_instance()


def persist_llm_usage(
    usage,
    model: str,
    call_type: str,
    stock_code=None,
) -> None:
    """Fire-and-forget: write one LLM call record to ``llm_usage``.

    Never raises - failures are logged at WARNING and swallowed.
    """
    try:
        db = DatabaseManager.get_instance()
        db.record_llm_usage(
            call_type=call_type,
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
            total_tokens=usage.get("total_tokens", 0) or 0,
            stock_code=stock_code,
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "[LLM usage] failed to persist usage record: %s", exc
        )
