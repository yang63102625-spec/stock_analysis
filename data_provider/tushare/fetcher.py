# -*- coding: utf-8 -*-
"""
TushareFetcher - composes the historical / realtime / market mixins on top
of ``_TushareCore`` (which provides ``__init__``, rate-limit and code
conversion helpers).

The MRO is:
    _RealtimeMixin -> _MarketMixin -> _HistoricalMixin -> _TushareCore
        -> RateLimitMixin -> BaseFetcher

Mixins are listed before the core so any future override can shadow base
behaviour while still chaining via ``super()`` if needed.
"""
from __future__ import annotations

import logging

from .base import _TushareCore
from .historical import _HistoricalMixin
from .market import _MarketMixin
from .realtime import _RealtimeMixin

logger = logging.getLogger(__name__)


class TushareFetcher(_RealtimeMixin, _MarketMixin, _HistoricalMixin, _TushareCore):
    """
    Tushare Pro 数据源实现。

    优先级：根据 token 是否配置动态调整（-1 最高 / 2 默认）
    数据来源：Tushare Pro API

    关键策略：
    - 每分钟调用计数器，防止超出配额（80 次/分钟）
    - 失败后指数退避重试
    - realtime_list / rt_k 全市场快照 + TTL 缓存
    """

    __doc__ += "\n\nSee ``data_provider.tushare`` package for split modules."


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    fetcher = TushareFetcher()

    try:
        df = fetcher.get_daily_data('600519')
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())

        name = fetcher.get_stock_name('600519')
        print(f"股票名称: {name}")

    except Exception as e:
        print(f"获取失败: {e}")

    print("\n" + "=" * 50)
    print("Testing get_market_stats (tushare)")
    print("=" * 50)
    try:
        stats = fetcher.get_market_stats()
        if stats:
            print("Market Stats successfully computed:")
            print(f"Up: {stats['up_count']} (Limit Up: {stats['limit_up_count']})")
            print(f"Down: {stats['down_count']} (Limit Down: {stats['limit_down_count']})")
            print(f"Flat: {stats['flat_count']}")
            print(f"Total Amount: {stats['total_amount']:.2f} 亿 (Yi)")
        else:
            print("Failed to compute market stats.")
    except Exception as e:
        print(f"Failed to compute market stats: {e}")
