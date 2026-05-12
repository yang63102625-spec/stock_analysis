# -*- coding: utf-8 -*-
"""Backward compatibility shim - actual implementation in src/notification_service/wechat_formatter.py"""
from src.notification_service.wechat_formatter import (  # noqa: F401
    PublishPlatform,
    WechatConfig,
    WechatFormatter,
)

__all__ = ["PublishPlatform", "WechatConfig", "WechatFormatter"]
