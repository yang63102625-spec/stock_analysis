# -*- coding: utf-8 -*-
"""Backward compatibility shim - actual implementation in src/notification_service/formatters.py"""
from src.notification_service.formatters import (  # noqa: F401
    TRUNCATION_SUFFIX,
    PAGE_MARKER_PREFIX,
    PAGE_MARKER_SAFE_BYTES,
    PAGE_MARKER_SAFE_LEN,
    MIN_MAX_WORDS,
    MIN_MAX_BYTES,
    markdown_to_html_document,
    markdown_to_plain_text,
    chunk_content_by_max_bytes,
    chunk_content_by_max_words,
    slice_at_max_bytes,
    format_feishu_markdown,
    # Internal helpers re-exported because ``tests/test_formatters.py`` imports
    # them via the legacy ``src.formatters`` path.
    _slice_at_effective_len,
    _chunk_by_max_words,
)

__all__ = [
    "TRUNCATION_SUFFIX",
    "PAGE_MARKER_PREFIX",
    "PAGE_MARKER_SAFE_BYTES",
    "PAGE_MARKER_SAFE_LEN",
    "MIN_MAX_WORDS",
    "MIN_MAX_BYTES",
    "markdown_to_html_document",
    "markdown_to_plain_text",
    "chunk_content_by_max_bytes",
    "chunk_content_by_max_words",
    "slice_at_max_bytes",
    "format_feishu_markdown",
]
