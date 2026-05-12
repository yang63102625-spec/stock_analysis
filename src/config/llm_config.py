# -*- coding: utf-8 -*-
"""LLM configuration parsing utilities.

Handles:
- LiteLLM YAML config file parsing
- LLM_CHANNELS env var parsing
- Legacy per-provider key to Router model_list conversion
- Shared LLM helpers (get_api_keys_for_model, extra_litellm_params)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML config parsing
# ---------------------------------------------------------------------------

def parse_litellm_yaml(config_path: str) -> List[Dict[str, Any]]:
    """Parse a standard LiteLLM config YAML file into Router model_list.

    Supports the ``os.environ/VAR_NAME`` syntax for secret references.
    Returns an empty list on any error (logged, never raises).
    """
    try:
        import yaml
    except ImportError:
        _logger.warning("PyYAML not installed; LITELLM_CONFIG ignored. Install with: pip install pyyaml")
        return []

    path = Path(config_path)
    if not path.is_absolute():
        # src/config/llm_config.py -> src/config/ -> src/ -> root
        path = Path(__file__).parent.parent.parent / path
    if not path.exists():
        _logger.warning(f"LITELLM_CONFIG file not found: {path}")
        return []

    try:
        with open(path, encoding='utf-8') as f:
            yaml_config = yaml.safe_load(f) or {}
    except Exception as e:
        _logger.warning(f"Failed to parse LITELLM_CONFIG: {e}")
        return []

    model_list = yaml_config.get('model_list', [])
    if not isinstance(model_list, list):
        _logger.warning("LITELLM_CONFIG: model_list must be a list")
        return []

    # Resolve os.environ/ references in string params
    for entry in model_list:
        params = entry.get('litellm_params', {})
        for key in list(params.keys()):
            val = params.get(key)
            if isinstance(val, str) and val.startswith('os.environ/'):
                env_name = val.split('/', 1)[1]
                params[key] = os.getenv(env_name, '')

    _logger.info(f"LITELLM_CONFIG: loaded {len(model_list)} model deployment(s) from {path}")
    return model_list


# ---------------------------------------------------------------------------
# Channel-based config parsing
# ---------------------------------------------------------------------------

def parse_llm_channels(channels_str: str) -> List[Dict[str, Any]]:
    """Parse LLM_CHANNELS env var and per-channel env vars.

    Format::

        LLM_CHANNELS=aihubmix,deepseek,gemini
        LLM_AIHUBMIX_BASE_URL=https://aihubmix.com/v1
        LLM_AIHUBMIX_API_KEY=sk-xxx           (or LLM_AIHUBMIX_API_KEYS=k1,k2)
        LLM_AIHUBMIX_MODELS=openai/gpt-4o-mini,openai/claude-3-5-sonnet
    """
    channels: List[Dict[str, Any]] = []
    for raw_name in channels_str.split(','):
        ch_name = raw_name.strip()
        if not ch_name:
            continue
        ch_upper = ch_name.upper()

        base_url = os.getenv(f'LLM_{ch_upper}_BASE_URL', '').strip() or None

        # API keys: LLM_{NAME}_API_KEYS (multi) > LLM_{NAME}_API_KEY (single)
        api_keys_raw = os.getenv(f'LLM_{ch_upper}_API_KEYS', '')
        api_keys = [k.strip() for k in api_keys_raw.split(',') if k.strip()]
        if not api_keys:
            single_key = os.getenv(f'LLM_{ch_upper}_API_KEY', '').strip()
            if single_key:
                api_keys = [single_key]

        # Models
        models_raw = os.getenv(f'LLM_{ch_upper}_MODELS', '')
        models = [m.strip() for m in models_raw.split(',') if m.strip()]
        # Auto-prefix: models without provider prefix in channels with base_url -> openai/
        models = [
            (f'openai/{m}' if '/' not in m and base_url else m)
            for m in models
        ]

        # Extra headers (JSON string, optional)
        extra_headers_raw = os.getenv(f'LLM_{ch_upper}_EXTRA_HEADERS', '').strip()
        extra_headers = None
        if extra_headers_raw:
            try:
                extra_headers = json.loads(extra_headers_raw)
            except json.JSONDecodeError:
                _logger.warning(f"LLM_{ch_upper}_EXTRA_HEADERS: invalid JSON, ignored")

        if not api_keys:
            _logger.warning(f"LLM channel '{ch_name}': no API key configured, skipped")
            continue
        if not models:
            _logger.warning(f"LLM channel '{ch_name}': no models configured, skipped")
            continue

        channels.append({
            'name': ch_name.lower(),
            'base_url': base_url,
            'api_keys': api_keys,
            'models': models,
            'extra_headers': extra_headers,
        })
        _logger.info(f"LLM channel '{ch_name}': {len(models)} model(s), {len(api_keys)} key(s)")

    return channels


def channels_to_model_list(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert parsed LLM channels to LiteLLM Router model_list format."""
    model_list: List[Dict[str, Any]] = []
    for ch in channels:
        for model_name in ch['models']:
            for api_key in ch['api_keys']:
                litellm_params: Dict[str, Any] = {
                    'model': model_name,
                    'api_key': api_key,
                }
                if ch['base_url']:
                    litellm_params['api_base'] = ch['base_url']
                # Auto-inject aihubmix sponsored header
                headers = dict(ch.get('extra_headers') or {})
                if ch['base_url'] and 'aihubmix.com' in ch['base_url']:
                    headers.setdefault('APP-Code', 'GPIJ3886')
                if headers:
                    litellm_params['extra_headers'] = headers

                model_list.append({
                    'model_name': model_name,
                    'litellm_params': litellm_params,
                })
    return model_list


# ---------------------------------------------------------------------------
# Legacy key -> model_list builder
# ---------------------------------------------------------------------------

def legacy_keys_to_model_list(
    gemini_keys: List[str],
    anthropic_keys: List[str],
    openai_keys: List[str],
    openai_base_url: Optional[str],
    deepseek_keys: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Build Router model_list from legacy per-provider keys (backward compat).

    Returns a model_list where each provider's keys are expanded into
    deployments, keyed by placeholder model_name tokens.  The analyzer
    resolves actual model_names at call time from LITELLM_MODEL /
    LITELLM_FALLBACK_MODELS.
    """
    model_list: List[Dict[str, Any]] = []

    # Gemini keys
    for k in gemini_keys:
        if k and len(k) >= 8:
            model_list.append({
                'model_name': '__legacy_gemini__',
                'litellm_params': {'model': '__legacy_gemini__', 'api_key': k},
            })

    # Anthropic keys
    for k in anthropic_keys:
        if k and len(k) >= 8:
            model_list.append({
                'model_name': '__legacy_anthropic__',
                'litellm_params': {'model': '__legacy_anthropic__', 'api_key': k},
            })

    # OpenAI-compatible keys
    for k in openai_keys:
        if k and len(k) >= 8:
            params: Dict[str, Any] = {'model': '__legacy_openai__', 'api_key': k}
            if openai_base_url:
                params['api_base'] = openai_base_url
            if openai_base_url and 'aihubmix.com' in openai_base_url:
                params['extra_headers'] = {'APP-Code': 'GPIJ3886'}
            model_list.append({
                'model_name': '__legacy_openai__',
                'litellm_params': params,
            })

    # DeepSeek keys (native litellm provider - auto-resolves api_base)
    for k in (deepseek_keys or []):
        if k and len(k) >= 8:
            model_list.append({
                'model_name': '__legacy_deepseek__',
                'litellm_params': {
                    'model': '__legacy_deepseek__',
                    'api_key': k,
                },
            })

    return model_list


# ---------------------------------------------------------------------------
# Shared LLM helpers (used by both analyzer and agent/llm_adapter)
# ---------------------------------------------------------------------------

def get_api_keys_for_model(model: str, config: Any) -> List[str]:
    """Return explicitly managed API keys for a litellm model (legacy path only).

    When llm_model_list is populated (channels / YAML), the Router handles key
    selection, so this function is not needed.  Kept for backward compat when
    no Router is built and a direct litellm.completion() call is needed.
    """
    if model.startswith("gemini/") or model.startswith("vertex_ai/"):
        return [k for k in config.gemini_api_keys if k and len(k) >= 8]
    if model.startswith("anthropic/"):
        return [k for k in config.anthropic_api_keys if k and len(k) >= 8]
    if model.startswith("deepseek/"):
        return [k for k in config.deepseek_api_keys if k and len(k) >= 8]
    if model.startswith("openai/") or "/" not in model:
        return [k for k in config.openai_api_keys if k and len(k) >= 8]
    # Other LiteLLM-native providers - API key resolved from env vars
    return []


def extra_litellm_params(model: str, config: Any) -> Dict[str, Any]:
    """Build extra litellm params for a model (legacy path only).

    When llm_model_list is populated, the Router already carries api_base
    and headers per-deployment, so this is not called.
    """
    params: Dict[str, Any] = {}
    # deepseek/ provider: litellm auto-resolves api_base, no manual override needed
    if model.startswith("deepseek/"):
        return params
    if model.startswith("openai/") or "/" not in model:
        if config.openai_base_url:
            params["api_base"] = config.openai_base_url
        if config.openai_base_url and "aihubmix.com" in config.openai_base_url:
            params["extra_headers"] = {"APP-Code": "GPIJ3886"}
    return params
