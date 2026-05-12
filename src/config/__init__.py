"""Configuration management package.

Maintains backward compatibility: ``from src.config import get_config, Config`` still works.
All public symbols previously available from ``src.config`` are re-exported here.
"""

from .base import Config, ConfigIssue, setup_env
from .loader import get_config, get_effective_push_report_type
from .llm_config import extra_litellm_params, get_api_keys_for_model

__all__ = [
    "Config",
    "ConfigIssue",
    "setup_env",
    "get_config",
    "get_effective_push_report_type",
    "get_api_keys_for_model",
    "extra_litellm_params",
]
