# -*- coding: utf-8 -*-
"""Akshare data provider subpackage (split from the legacy single-file module)."""
from .fetcher import AkshareFetcher
from .utils import is_hk_stock_code

__all__ = ["AkshareFetcher", "is_hk_stock_code"]
