# -*- coding: utf-8 -*-
"""``EfinanceFetcher`` — concrete data source composed from base + mixins."""
from __future__ import annotations

from .base import _EfinanceCore
from .historical import _HistoricalMixin
from .market import _MarketMixin
from .realtime import _RealtimeMixin


class EfinanceFetcher(_RealtimeMixin, _MarketMixin, _HistoricalMixin, _EfinanceCore):
    """Highest-priority Eastmoney data source (priority=0).

    Composition mirrors the ``Akshare`` / ``Tushare`` layout: each mixin
    owns a logical slice (historical / realtime / market) and the core
    base class supplies ``__init__`` + dispatch.
    """


__all__ = ["EfinanceFetcher"]
