# -*- coding: utf-8 -*-
"""A-share AI analysis layer.

Public surface (re-exported from internal sub-modules):

- ``AnalysisResult``: structured analysis result data class.
- ``GeminiAnalyzer``: LLM analyzer (LiteLLM-backed) with retry / parsing.
- ``get_analyzer``: factory returning a default :class:`GeminiAnalyzer`.
- ``check_content_integrity`` / ``apply_placeholder_fill`` /
  ``fill_chip_structure_if_needed``: report-content integrity helpers.
- ``get_stock_name_multi_source``: stock-name resolver used by reports.
- ``get_config``: re-exported here so existing tests can ``patch``
  ``src.analyzer.get_config``.
"""

from src.config import get_config  # noqa: F401  (test patch target)

from .integrity import (
    _build_chip_structure_from_data,
    _derive_chip_health,
    _is_value_placeholder,
    apply_placeholder_fill,
    check_content_integrity,
    fill_chip_structure_if_needed,
)
from .result import AnalysisResult
from .stock_name import get_stock_name_multi_source
from .gemini import GeminiAnalyzer, get_analyzer

__all__ = [
    "AnalysisResult",
    "GeminiAnalyzer",
    "get_analyzer",
    "get_config",
    "check_content_integrity",
    "apply_placeholder_fill",
    "fill_chip_structure_if_needed",
    "get_stock_name_multi_source",
]
