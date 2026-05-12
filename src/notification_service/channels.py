# -*- coding: utf-8 -*-
"""
Channel dispatch mixin for NotificationService.

Contains channel detection, context channel handling, and the unified
send() dispatch logic.
"""
import logging
from typing import Any, Dict, List, Optional

from bot.models import BotMessage
from src.config import get_config
from src.notification_sender import WECHAT_IMAGE_MAX_BYTES

logger = logging.getLogger(__name__)


class ChannelDispatcherMixin:
    """
    Mixin that provides channel detection and dispatch methods.

    Expects the host class to have:
      - self._source_message: Optional[BotMessage]
      - self._available_channels: List[NotificationChannel]
      - self._context_channels: List[str]
      - self._markdown_to_image_channels: set
      - self._markdown_to_image_max_chars: int
      - All sender mixin methods (send_to_wechat, send_to_feishu, etc.)
    """

    def _detect_all_channels(self) -> list:
        """
        Detect all configured notification channels.

        Returns:
            List of configured NotificationChannel enums
        """
        from src.notification_service.service import NotificationChannel

        channels = []

        # WeChat Work
        if self._wechat_url:
            channels.append(NotificationChannel.WECHAT)

        # Feishu
        if self._feishu_url:
            channels.append(NotificationChannel.FEISHU)

        # Telegram
        if self._is_telegram_configured():
            channels.append(NotificationChannel.TELEGRAM)

        # Email
        if self._is_email_configured():
            channels.append(NotificationChannel.EMAIL)

        # Pushover
        if self._is_pushover_configured():
            channels.append(NotificationChannel.PUSHOVER)

        # PushPlus
        if self._pushplus_token:
            channels.append(NotificationChannel.PUSHPLUS)

       # Server酱3
        if self._serverchan3_sendkey:
            channels.append(NotificationChannel.SERVERCHAN3)

        # Custom Webhook
        if self._custom_webhook_urls:
            channels.append(NotificationChannel.CUSTOM)

        # Discord
        if self._is_discord_configured():
            channels.append(NotificationChannel.DISCORD)
        # AstrBot
        if self._is_astrbot_configured():
            channels.append(NotificationChannel.ASTRBOT)
        return channels

    def is_available(self) -> bool:
        """Check if notification service is available (at least one channel or context channel)."""
        return len(self._available_channels) > 0 or self._has_context_channel()

    def get_available_channels(self) -> list:
        """Get all configured channels."""
        return self._available_channels

    def get_channel_names(self) -> str:
        """Get names of all configured channels."""
        from src.notification_service.service import ChannelDetector, NotificationChannel
        names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
        if self._has_context_channel():
            names.append("钉钉会话")
        return ', '.join(names)

    # ===== Context channel =====
    def _has_context_channel(self) -> bool:
        """Check if context-based temporary channels exist (e.g. DingTalk session, Feishu session)."""
        return (
            self._extract_dingtalk_session_webhook() is not None
            or self._extract_feishu_reply_info() is not None
        )

    def _extract_dingtalk_session_webhook(self) -> Optional[str]:
        """Extract DingTalk session webhook from source message (for Stream mode reply)."""
        if not isinstance(self._source_message, BotMessage):
            return None
        raw_data = getattr(self._source_message, "raw_data", {}) or {}
        if not isinstance(raw_data, dict):
            return None
        session_webhook = (
            raw_data.get("_session_webhook")
            or raw_data.get("sessionWebhook")
            or raw_data.get("session_webhook")
            or raw_data.get("session_webhook_url")
        )
        if not session_webhook and isinstance(raw_data.get("headers"), dict):
            session_webhook = raw_data["headers"].get("sessionWebhook")
        return session_webhook

    def _extract_feishu_reply_info(self) -> Optional[Dict[str, str]]:
        """
        Extract Feishu reply info from source message (for Stream mode reply).

        Returns:
            Dict with chat_id, or None
        """
        if not isinstance(self._source_message, BotMessage):
            return None
        if getattr(self._source_message, "platform", "") != "feishu":
            return None
        chat_id = getattr(self._source_message, "chat_id", "")
        if not chat_id:
            return None
        return {"chat_id": chat_id}

    def send_to_context(self, content: str) -> bool:
        """
        Send message to context-based channels (e.g. DingTalk Stream session).

        Args:
            content: Markdown format content
        """
        return self._send_via_source_context(content)

    def _send_via_source_context(self, content: str) -> bool:
        """
        Send report using message context (e.g. DingTalk/Feishu session).

        Mainly used for tasks triggered from bot Stream mode, ensuring results
        return to the triggering session.
        """
        success = False

        # Try DingTalk session
        session_webhook = self._extract_dingtalk_session_webhook()
        if session_webhook:
            try:
                if self._send_dingtalk_chunked(session_webhook, content, max_bytes=20000):
                    logger.info("已通过钉钉会话（Stream）推送报告")
                    success = True
                else:
                    logger.error("钉钉会话（Stream）推送失败")
            except Exception as e:
                logger.error(f"钉钉会话（Stream）推送异常: {e}")

        # Try Feishu session
        feishu_info = self._extract_feishu_reply_info()
        if feishu_info:
            try:
                if self._send_feishu_stream_reply(feishu_info["chat_id"], content):
                    logger.info("已通过飞书会话（Stream）推送报告")
                    success = True
                else:
                    logger.error("飞书会话（Stream）推送失败")
            except Exception as e:
                logger.error(f"飞书会话（Stream）推送异常: {e}")

        return success

    def _send_feishu_stream_reply(self, chat_id: str, content: str) -> bool:
        """
        Send message to Feishu session via Stream mode.

        Args:
            chat_id: Feishu chat ID
            content: Message content

        Returns:
            Whether send was successful
        """
        try:
            from bot.platforms.feishu_stream import FeishuReplyClient, FEISHU_SDK_AVAILABLE
            if not FEISHU_SDK_AVAILABLE:
                logger.warning("飞书 SDK 不可用，无法发送 Stream 回复")
                return False

            from src.config import get_config
            config = get_config()

            app_id = getattr(config, 'feishu_app_id', None)
            app_secret = getattr(config, 'feishu_app_secret', None)

            if not app_id or not app_secret:
                logger.warning("飞书 APP_ID 或 APP_SECRET 未配置")
                return False

            reply_client = FeishuReplyClient(app_id, app_secret)

            max_bytes = getattr(config, 'feishu_max_bytes', 20000)
            content_bytes = len(content.encode('utf-8'))

            if content_bytes > max_bytes:
                return self._send_feishu_stream_chunked(reply_client, chat_id, content, max_bytes)

            return reply_client.send_to_chat(chat_id, content)

        except ImportError as e:
            logger.error(f"导入飞书 Stream 模块失败: {e}")
            return False
        except Exception as e:
            logger.error(f"飞书 Stream 回复异常: {e}")
            return False

    def _send_feishu_stream_chunked(
        self,
        reply_client,
        chat_id: str,
        content: str,
        max_bytes: int
    ) -> bool:
        """
        Send long messages to Feishu in chunks (Stream mode).

        Args:
            reply_client: FeishuReplyClient instance
            chat_id: Feishu chat ID
            content: Full message content
            max_bytes: Max bytes per message

        Returns:
            Whether all chunks sent successfully
        """
        import time

        def get_bytes(s: str) -> int:
            return len(s.encode('utf-8'))

        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            sections = content.split("\n")
            separator = "\n"

        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)

        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes

            if current_bytes + section_bytes > max_bytes:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes

        if current_chunk:
            chunks.append(separator.join(current_chunk))

        success = True
        for i, chunk in enumerate(chunks):
            if i > 0:
                time.sleep(0.5)

            if not reply_client.send_to_chat(chat_id, chunk):
                success = False
                logger.error(f"飞书 Stream 分块 {i+1}/{len(chunks)} 发送失败")

        return success

    def _should_use_image_for_channel(
        self, channel, image_bytes: Optional[bytes]
    ) -> bool:
        """
        Decide whether to send as image for the given channel (Issue #289).

        Fallback rules (send as Markdown text instead of image):
        - image_bytes is None: conversion failed / imgkit not installed / content over max_chars
        - WeChat: image exceeds ~2MB limit
        """
        from src.notification_service.service import NotificationChannel

        if channel.value not in self._markdown_to_image_channels or image_bytes is None:
            return False
        if channel == NotificationChannel.WECHAT and len(image_bytes) > WECHAT_IMAGE_MAX_BYTES:
            logger.warning(
                "企业微信图片超限 (%d bytes)，回退为 Markdown 文本发送",
                len(image_bytes),
            )
            return False
        return True

    def send(
        self,
        content: str,
        email_stock_codes: Optional[List[str]] = None,
        email_send_to_all: bool = False
    ) -> bool:
        """
        Unified send interface - send to all configured channels.

        Iterates all configured channels and sends message to each one.

        Fallback rules (Markdown-to-image, Issue #289):
        - When image_bytes is None (conversion failed / imgkit not installed /
          content over max_chars): all channels configured for image will send
          as Markdown text instead.
        - When WeChat image exceeds ~2MB: that channel falls back to Markdown text.

        Args:
            content: Message content (Markdown format)
            email_stock_codes: Stock codes (optional, for email channel routing, Issue #268)
            email_send_to_all: Whether email goes to all configured addresses

        Returns:
            Whether at least one channel sent successfully
        """
        from src.notification_service.service import NotificationChannel, ChannelDetector

        context_success = self.send_to_context(content)

        if not self._available_channels:
            if context_success:
                logger.info("已通过消息上下文渠道完成推送（无其他通知渠道）")
                return True
            logger.warning("通知服务不可用，跳过推送")
            return False

        # Markdown to image (Issue #289): convert once if any channel needs it.
        image_bytes = None
        channels_needing_image = {
            ch for ch in self._available_channels
            if ch.value in self._markdown_to_image_channels
        }
        if channels_needing_image:
            from src.md2img import markdown_to_image
            image_bytes = markdown_to_image(
                content, max_chars=self._markdown_to_image_max_chars
            )
            if image_bytes:
                logger.info("Markdown 已转换为图片，将向 %s 发送图片",
                            [ch.value for ch in channels_needing_image])
            elif channels_needing_image:
                try:
                    from src.config import get_config
                    engine = getattr(get_config(), "md2img_engine", "wkhtmltoimage")
                except Exception:
                    engine = "wkhtmltoimage"
                hint = (
                    "npm i -g markdown-to-file" if engine == "markdown-to-file"
                    else "wkhtmltopdf (apt install wkhtmltopdf / brew install wkhtmltopdf)"
                )
                logger.warning(
                    "Markdown 转图片失败，将回退为文本发送。请检查 MARKDOWN_TO_IMAGE_CHANNELS 配置并安装 %s",
                    hint,
                )

        channel_names = self.get_channel_names()
        logger.info(f"正在向 {len(self._available_channels)} 个渠道发送通知：{channel_names}")

        success_count = 0
        fail_count = 0

        for channel in self._available_channels:
            channel_name = ChannelDetector.get_channel_name(channel)
            use_image = self._should_use_image_for_channel(channel, image_bytes)
            try:
                if channel == NotificationChannel.WECHAT:
                    if use_image:
                        result = self._send_wechat_image(image_bytes)
                    else:
                        result = self.send_to_wechat(content)
                elif channel == NotificationChannel.FEISHU:
                    result = self.send_to_feishu(content)
                elif channel == NotificationChannel.TELEGRAM:
                    if use_image:
                        result = self._send_telegram_photo(image_bytes)
                    else:
                        result = self.send_to_telegram(content)
                elif channel == NotificationChannel.EMAIL:
                    receivers = None
                    if email_send_to_all and self._stock_email_groups:
                        receivers = self.get_all_email_receivers()
                    elif email_stock_codes and self._stock_email_groups:
                        receivers = self.get_receivers_for_stocks(email_stock_codes)
                    if use_image:
                        result = self._send_email_with_inline_image(
                            image_bytes, receivers=receivers
                        )
                    else:
                        result = self.send_to_email(content, receivers=receivers)
                elif channel == NotificationChannel.PUSHOVER:
                    result = self.send_to_pushover(content)
                elif channel == NotificationChannel.PUSHPLUS:
                    result = self.send_to_pushplus(content)
                elif channel == NotificationChannel.SERVERCHAN3:
                    result = self.send_to_serverchan3(content)
                elif channel == NotificationChannel.CUSTOM:
                    if use_image:
                        result = self._send_custom_webhook_image(
                            image_bytes, fallback_content=content
                        )
                    else:
                        result = self.send_to_custom(content)
                elif channel == NotificationChannel.DISCORD:
                    result = self.send_to_discord(content)
                elif channel == NotificationChannel.ASTRBOT:
                    result = self.send_to_astrbot(content)
                else:
                    logger.warning(f"不支持的通知渠道: {channel}")
                    result = False

                if result:
                    success_count += 1
                else:
                    fail_count += 1

            except Exception as e:
                logger.error(f"{channel_name} 发送失败: {e}")
                fail_count += 1

        logger.info(f"通知发送完成：成功 {success_count} 个，失败 {fail_count} 个")
        return success_count > 0 or context_success

    def save_report_to_file(
        self,
        content: str,
        filename: Optional[str] = None
    ) -> str:
        """
        Save report to local file.

        Args:
            content: Report content
            filename: Filename (optional, defaults to date-based)

        Returns:
            Saved file path
        """
        from datetime import datetime
        from pathlib import Path

        if filename is None:
            date_str = datetime.now().strftime('%Y%m%d')
            filename = f"report_{date_str}.md"

        # Ensure reports directory exists (under project root)
        reports_dir = Path(__file__).parent.parent.parent / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)

        filepath = reports_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info(f"日报已保存到: {filepath}")
        return str(filepath)
