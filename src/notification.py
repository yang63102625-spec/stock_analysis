# -*- coding: utf-8 -*-
"""Backward compatibility shim - actual implementation in src/notification_service/"""
from src.notification_service import (  # noqa: F401
    NotificationService,
    NotificationChannel,
    NotificationBuilder,
    ChannelDetector,
)

__all__ = ["NotificationService", "NotificationChannel", "NotificationBuilder", "ChannelDetector"]
