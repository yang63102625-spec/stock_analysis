# -*- coding: utf-8 -*-
"""
NotificationService - main coordinator class.

Composes the sender mixins, report aggregator mixin, and channel dispatcher mixin.
"""
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.analyzer import AnalysisResult
from src.config import get_config
from bot.models import BotMessage
from src.notification_sender import (
    AstrbotSender,
    CustomWebhookSender,
    DiscordSender,
    EmailSender,
    FeishuSender,
    PushoverSender,
    PushplusSender,
    Serverchan3Sender,
    TelegramSender,
    WechatSender,
    WECHAT_IMAGE_MAX_BYTES,
)
from src.notification_service.aggregator import ReportAggregatorMixin
from src.notification_service.channels import ChannelDispatcherMixin

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """Notification channel types."""
    WECHAT = "wechat"      # WeChat Work
    FEISHU = "feishu"      # Feishu / Lark
    TELEGRAM = "telegram"  # Telegram
    EMAIL = "email"        # Email
    PUSHOVER = "pushover"  # Pushover (mobile/desktop push)
    PUSHPLUS = "pushplus"  # PushPlus (China push service)
    SERVERCHAN3 = "serverchan3"  # Server酱3 (mobile APP push)
    CUSTOM = "custom"      # Custom Webhook
    DISCORD = "discord"    # Discord Bot
    ASTRBOT = "astrbot"
    UNKNOWN = "unknown"    # Unknown


class ChannelDetector:
    """
    Channel detector - simplified version.

    Determines channel type directly from configuration (no URL parsing needed).
    """

    @staticmethod
    def get_channel_name(channel: NotificationChannel) -> str:
        """Get channel display name (Chinese)."""
        names = {
            NotificationChannel.WECHAT: "企业微信",
            NotificationChannel.FEISHU: "飞书",
            NotificationChannel.TELEGRAM: "Telegram",
            NotificationChannel.EMAIL: "邮件",
            NotificationChannel.PUSHOVER: "Pushover",
            NotificationChannel.PUSHPLUS: "PushPlus",
            NotificationChannel.SERVERCHAN3: "Server酱3",
            NotificationChannel.CUSTOM: "自定义Webhook",
            NotificationChannel.DISCORD: "Discord机器人",
            NotificationChannel.ASTRBOT: "ASTRBOT机器人",
            NotificationChannel.UNKNOWN: "未知渠道",
        }
        return names.get(channel, "未知渠道")


class NotificationService(
    ReportAggregatorMixin,
    ChannelDispatcherMixin,
    AstrbotSender,
    CustomWebhookSender,
    DiscordSender,
    EmailSender,
    FeishuSender,
    PushoverSender,
    PushplusSender,
    Serverchan3Sender,
    TelegramSender,
    WechatSender
):
    """
    Notification service.

    Responsibilities:
    1. Generate Markdown formatted analysis reports
    2. Push messages to all configured channels (multi-channel)
    3. Support local report saving

    Supported channels:
    - WeChat Work Webhook
    - Feishu Webhook
    - Telegram Bot
    - Email SMTP
    - Pushover (mobile/desktop push)

    Note: All configured channels will receive the push.
    """

    def __init__(self, source_message: Optional[BotMessage] = None):
        """
        Initialize notification service.

        Detects all configured channels; pushes to all channels when sending.
        """
        config = get_config()
        self._source_message = source_message
        self._context_channels: List[str] = []

        # Markdown to image (Issue #289)
        self._markdown_to_image_channels = set(
            getattr(config, 'markdown_to_image_channels', []) or []
        )
        self._markdown_to_image_max_chars = getattr(
            config, 'markdown_to_image_max_chars', 15000
        )

        # Summary only mode (Issue #262): only push summary, no per-stock details
        self._report_summary_only = getattr(config, 'report_summary_only', False)
        self._history_compare_cache: Dict[Tuple[int, Tuple[Tuple[str, str], ...]], Dict[str, List[Dict[str, Any]]]] = {}

        # Initialize each channel sender
        AstrbotSender.__init__(self, config)
        CustomWebhookSender.__init__(self, config)
        DiscordSender.__init__(self, config)
        EmailSender.__init__(self, config)
        FeishuSender.__init__(self, config)
        PushoverSender.__init__(self, config)
        PushplusSender.__init__(self, config)
        Serverchan3Sender.__init__(self, config)
        TelegramSender.__init__(self, config)
        WechatSender.__init__(self, config)

        # Detect all configured channels
        self._available_channels = self._detect_all_channels()
        if self._has_context_channel():
            self._context_channels.append("钉钉会话")

        if not self._available_channels and not self._context_channels:
            logger.warning("未配置有效的通知渠道，将不发送推送通知")
        else:
            channel_names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
            channel_names.extend(self._context_channels)
            logger.info(f"已配置 {len(channel_names)} 个通知渠道：{', '.join(channel_names)}")


class NotificationBuilder:
    """
    Notification message builder.

    Provides convenient message building methods.
    """

    @staticmethod
    def build_simple_alert(
        title: str,
        content: str,
        alert_type: str = "info"
    ) -> str:
        """
        Build a simple alert message.

        Args:
            title: Title
            content: Content
            alert_type: Type (info, warning, error, success)
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        emoji = emoji_map.get(alert_type, "📢")

        return f"{emoji} **{title}**\n\n{content}"

    @staticmethod
    def build_stock_summary(results: List[AnalysisResult]) -> str:
        """
        Build stock summary (short version).

        Suitable for quick notifications.
        """
        lines = ["📊 **今日自选股摘要**", ""]

        for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
            emoji = r.get_emoji()
            lines.append(f"{emoji} {r.name}({r.code}): {r.operation_advice} | 评分 {r.sentiment_score}")

        return "\n".join(lines)
