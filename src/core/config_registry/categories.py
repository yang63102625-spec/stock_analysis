# -*- coding: utf-8 -*-
"""Category-level metadata + schema version constant."""
from __future__ import annotations

from typing import Any, Dict, List


SCHEMA_VERSION = "2026-02-09"

_CATEGORY_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "category": "base",
        "title": "Base Settings",
        "description": "Watchlist and foundational application settings.",
        "display_order": 10,
    },
    {
        "category": "ai_model",
        "title": "AI Model",
        "description": "Model providers, model names, and inference parameters.",
        "display_order": 20,
    },
    {
        "category": "data_source",
        "title": "Data Source",
        "description": "Market data provider credentials and priority settings.",
        "display_order": 30,
    },
    {
        "category": "notification",
        "title": "Notification",
        "description": "Bot, webhook, and push channel related settings.",
        "display_order": 40,
    },
    {
        "category": "system",
        "title": "System",
        "description": "Runtime and scheduling controls.",
        "display_order": 50,
    },
    {
        "category": "backtest",
        "title": "Backtest",
        "description": "Backtest engine behavior and evaluation parameters.",
        "display_order": 60,
    },
    {
        "category": "uncategorized",
        "title": "Uncategorized",
        "description": "Keys not mapped in the field registry.",
        "display_order": 99,
    },
]
