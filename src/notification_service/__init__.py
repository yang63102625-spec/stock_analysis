# -*- coding: utf-8 -*-
"""
Notification service subpackage.

Re-exports the public API so callers can do:
    from src.notification_service import NotificationService
"""
from src.notification_service.service import (  # noqa: F401
    NotificationChannel,
    NotificationService,
    NotificationBuilder,
    ChannelDetector,
)

__all__ = [
    "NotificationService",
    "NotificationChannel",
    "NotificationBuilder",
    "ChannelDetector",
]
