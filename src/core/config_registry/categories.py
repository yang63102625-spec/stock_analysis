# -*- coding: utf-8 -*-
"""Category-level metadata + schema version constant."""
from __future__ import annotations

from typing import Any, Dict, List


SCHEMA_VERSION = "2026-02-09"

_CATEGORY_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "category": "base",
        "title": "Base Settings",
        "title_zh": "基础设置",
        "description": "Watchlist and foundational application settings.",
        "description_zh": "管理自选股与基础运行参数。",
        "display_order": 10,
    },
    {
        "category": "ai_model",
        "title": "AI Model",
        "title_zh": "AI 模型",
        "description": "Model providers, model names, and inference parameters.",
        "description_zh": "管理模型供应商、模型名称与推理参数。",
        "display_order": 20,
    },
    {
        "category": "data_source",
        "title": "Data Source",
        "title_zh": "数据源",
        "description": "Market data provider credentials and priority settings.",
        "description_zh": "管理行情数据源与优先级策略。",
        "display_order": 30,
    },
    {
        "category": "notification",
        "title": "Notification",
        "title_zh": "通知渠道",
        "description": "Bot, webhook, and push channel related settings.",
        "description_zh": "管理机器人、Webhook 和消息推送配置。",
        "display_order": 40,
    },
    {
        "category": "system",
        "title": "System",
        "title_zh": "系统设置",
        "description": "Runtime and scheduling controls.",
        "description_zh": "管理调度、日志、端口等系统级参数。",
        "display_order": 50,
    },
    {
        "category": "backtest",
        "title": "Backtest",
        "title_zh": "回测配置",
        "description": "Backtest engine behavior and evaluation parameters.",
        "description_zh": "管理回测开关、评估窗口和引擎参数。",
        "display_order": 60,
    },
    {
        "category": "uncategorized",
        "title": "Uncategorized",
        "title_zh": "其他",
        "description": "Keys not mapped in the field registry.",
        "description_zh": "其他未归类的配置项。",
        "display_order": 99,
    },
]
