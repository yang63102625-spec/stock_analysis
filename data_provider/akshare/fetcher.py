# -*- coding: utf-8 -*-
"""
AkshareFetcher - composes the historical / realtime / market mixins on top
of ``_AkshareCore``. See ``data_provider.akshare`` for the split modules.
"""
from __future__ import annotations

import logging

from .base import _AkshareCore
from .historical import _HistoricalMixin
from .market import _MarketMixin
from .realtime import _RealtimeMixin

logger = logging.getLogger(__name__)


class AkshareFetcher(_RealtimeMixin, _MarketMixin, _HistoricalMixin, _AkshareCore):
    """
    Akshare 数据源实现。

    优先级：1（最高）
    数据来源：东方财富/新浪/腾讯爬虫
    """

    __doc__ += "\n\nSee ``data_provider.akshare`` package for split modules."
