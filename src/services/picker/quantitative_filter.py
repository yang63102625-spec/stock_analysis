# -*- coding: utf-8 -*-
"""Backward-compatibility shim.

The ``StockScreener`` implementation now lives in
``src.services.picker.screener`` (split into base / data_fetch /
filters_scoring / pipeline / eod_buyback mixins). Existing imports such as
``from src.services.picker.quantitative_filter import StockScreener`` keep
working through this shim.
"""
from src.services.picker.screener import StockScreener  # noqa: F401

__all__ = ["StockScreener"]
