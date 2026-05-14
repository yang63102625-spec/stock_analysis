# -*- coding: utf-8 -*-
"""LLM client mixin: LiteLLM Router init, key rotation, generate_text."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

import litellm
from litellm import Router

litellm.set_verbose = False
litellm.suppress_debug_info = True

from src.agent.llm_adapter import get_thinking_extra_body
from src.config import Config, extra_litellm_params, get_api_keys_for_model, get_config
from src.storage import persist_llm_usage

logger = logging.getLogger(__name__)


class _LLMClientMixin:
    """Methods related to LiteLLM Router initialisation and chat invocation."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize LLM Analyzer via LiteLLM.

        Args:
            api_key: Ignored (kept for backward compatibility). Keys are loaded from config.
        """
        self._router = None
        self._litellm_available = False
        self._init_litellm()
        if not self._litellm_available:
            logger.warning("No LLM configured (LITELLM_MODEL / API keys), AI analysis will be unavailable")

    def _has_channel_config(self, config: Config) -> bool:
        """Check if multi-channel config (channels / YAML / legacy model_list) is active."""
        return bool(config.llm_model_list) and not all(
            e.get('model_name', '').startswith('__legacy_') for e in config.llm_model_list
        )

    def _init_litellm(self) -> None:
        """Initialize litellm Router from channels / YAML / legacy keys."""
        config = get_config()
        litellm_model = config.litellm_model
        if not litellm_model:
            logger.warning("Analyzer LLM: LITELLM_MODEL not configured")
            return

        self._litellm_available = True

        # --- Channel / YAML path: build Router from pre-built model_list ---
        if self._has_channel_config(config):
            model_list = config.llm_model_list
            self._router = Router(
                model_list=model_list,
                routing_strategy="simple-shuffle",
                num_retries=2,
            )
            unique_models = list(dict.fromkeys(
                e['litellm_params']['model'] for e in model_list
            ))
            logger.info(
                f"Analyzer LLM: Router initialized from channels/YAML — "
                f"{len(model_list)} deployment(s), models: {unique_models}"
            )
            return

        # --- Legacy path: build Router for multi-key, or use single key ---
        keys = get_api_keys_for_model(litellm_model, config)

        if len(keys) > 1:
            # Build legacy Router for primary model multi-key load-balancing
            extra_params = extra_litellm_params(litellm_model, config)
            legacy_model_list = [
                {
                    "model_name": litellm_model,
                    "litellm_params": {
                        "model": litellm_model,
                        "api_key": k,
                        **extra_params,
                    },
                }
                for k in keys
            ]
            self._router = Router(
                model_list=legacy_model_list,
                routing_strategy="simple-shuffle",
                num_retries=2,
            )
            logger.info(
                f"Analyzer LLM: Legacy Router initialized with {len(keys)} keys "
                f"for {litellm_model}"
            )
        elif keys:
            logger.info(f"Analyzer LLM: litellm initialized (model={litellm_model})")
        else:
            logger.info(
                f"Analyzer LLM: litellm initialized (model={litellm_model}, "
                f"API key from environment)"
            )

    def is_available(self) -> bool:
        """Check if LiteLLM is properly configured with at least one API key."""
        return self._router is not None or self._litellm_available

    def _call_litellm(self, prompt: str, generation_config: dict) -> Tuple[str, str, Dict[str, Any]]:
        """Call LLM via litellm with fallback across configured models.

        When channels/YAML are configured, every model goes through the Router
        (which handles per-model key selection, load balancing, and retries).
        In legacy mode, the primary model may use the Router while fallback
        models fall back to direct litellm.completion().

        Args:
            prompt: User prompt text.
            generation_config: Dict with optional keys: temperature, max_output_tokens, max_tokens.

        Returns:
            Tuple of (response text, model_used, usage). On success model_used is the full model
            name and usage is a dict with prompt_tokens, completion_tokens, total_tokens.
        """
        config = get_config()
        max_tokens = (
            generation_config.get('max_output_tokens')
            or generation_config.get('max_tokens')
            or 8192
        )
        temperature = generation_config.get('temperature', 0.7)

        models_to_try = [config.litellm_model] + (config.litellm_fallback_models or [])
        models_to_try = [m for m in models_to_try if m]

        use_channel_router = self._has_channel_config(config)

        last_error = None
        for model in models_to_try:
            try:
                model_short = model.split("/")[-1] if "/" in model else model
                call_kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                extra = get_thinking_extra_body(model_short)
                if extra:
                    call_kwargs["extra_body"] = extra

                if use_channel_router and self._router:
                    # Channel / YAML path: Router manages key + base_url per model
                    response = self._router.completion(**call_kwargs)
                elif self._router and model == config.litellm_model:
                    # Legacy path: Router only for primary model multi-key
                    response = self._router.completion(**call_kwargs)
                else:
                    # Legacy path: direct call for fallback models
                    keys = get_api_keys_for_model(model, config)
                    if keys:
                        call_kwargs["api_key"] = keys[0]
                    call_kwargs.update(extra_litellm_params(model, config))
                    response = litellm.completion(**call_kwargs)

                if response and response.choices and response.choices[0].message.content:
                    usage: Dict[str, Any] = {}
                    if response.usage:
                        usage = {
                            "prompt_tokens": response.usage.prompt_tokens or 0,
                            "completion_tokens": response.usage.completion_tokens or 0,
                            "total_tokens": response.usage.total_tokens or 0,
                        }
                    return (response.choices[0].message.content, model, usage)

                # Diagnose empty content – check if reasoning_content was produced
                msg = response.choices[0].message if (response and response.choices) else None
                reasoning = getattr(msg, "reasoning_content", None) if msg else None
                if reasoning:
                    logger.warning(
                        "[LiteLLM] %s returned empty content but has reasoning_content "
                        "(len=%d). Token budget likely exhausted by reasoning.",
                        model, len(reasoning),
                    )
                raise ValueError("LLM returned empty response")

            except Exception as e:
                logger.warning(f"[LiteLLM] {model} failed: {e}")
                last_error = e
                continue

        raise Exception(f"All LLM models failed (tried {len(models_to_try)} model(s)). Last error: {last_error}")

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> Optional[str]:
        """Public entry point for free-form text generation.

        External callers (e.g. MarketAnalyzer) must use this method instead of
        calling _call_litellm() directly or accessing private attributes such as
        _litellm_available, _router, _model, _use_openai, or _use_anthropic.

        Args:
            prompt:      Text prompt to send to the LLM.
            max_tokens:  Maximum tokens in the response (default 2048).
            temperature: Sampling temperature (default 0.7).

        Returns:
            Response text, or None if the LLM call fails (error is logged).
        """
        try:
            result = self._call_litellm(
                prompt,
                generation_config={"max_tokens": max_tokens, "temperature": temperature},
            )
            if isinstance(result, tuple):
                text, model_used, usage = result
                persist_llm_usage(usage, model_used, call_type="market_review")
                return text
            return result
        except Exception as exc:
            logger.error("[generate_text] LLM call failed: %s", exc)
            return None

