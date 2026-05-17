# -*- coding: utf-8 -*-
"""
``StockScreener`` - composes pipeline / data-fetch / filter-scoring mixins
on top of ``_ScreenerBase``. Every concern lives in its own module under
``src.services.picker.screener``.
"""
from __future__ import annotations

import logging

from .base import _ScreenerBase
from .bottom_reversal_v2 import _BottomReversalV2Mixin
from .data_fetch import _DataFetchMixin
from .filters_scoring import _FilterScoringMixin
from .pipeline import _PipelineMixin
from .reversal_breakout import _ReversalBreakoutMixin
from .slow_bull import _SlowBullMixin
from .small_cap import _SmallCapMixin

logger = logging.getLogger(__name__)


class StockScreener(
    _PipelineMixin,
    _FilterScoringMixin,
    _DataFetchMixin,
    _SmallCapMixin,
    _SlowBullMixin,
    _BottomReversalV2Mixin,
    _ReversalBreakoutMixin,
    _ScreenerBase,
):
    """Multi-layer quantitative screener using full-market spot data.

    The class body is intentionally empty; behaviour comes from the mixins.
    """

    __doc__ += "\n\nSee ``src.services.picker.screener`` package for the split modules."
