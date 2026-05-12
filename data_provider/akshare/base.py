# -*- coding: utf-8 -*-
"""Core ``AkshareFetcher`` setup: constructor, name/priority, eastmoney patch."""
from __future__ import annotations

import logging
import os
from typing import Optional

from patch.eastmoney_patch import eastmoney_patch
from src.config import get_config

from ..base import BaseFetcher
from ..rate_limit_mixin import RateLimitMixin

logger = logging.getLogger(__name__)


class _AkshareCore(RateLimitMixin, BaseFetcher):
    """Anchor class that owns the constructor and identification metadata.

    Mixins in the package extend this class to keep ``self._rate_limit_*``,
    the eastmoney monkey-patch and the priority constant centralised.
    """

    name = "AkshareFetcher"
    priority = int(os.getenv("AKSHARE_PRIORITY", "1"))

    def __init__(self, sleep_min: float = 2.0, sleep_max: float = 5.0):
        """Initialise AkshareFetcher.

        Args:
            sleep_min: Minimum random sleep before each request, in seconds.
            sleep_max: Maximum random sleep before each request, in seconds.
        """
        self._rate_limit_min = sleep_min
        self._rate_limit_max = sleep_max
        self._last_request_time: Optional[float] = None
        if get_config().enable_eastmoney_patch:
            eastmoney_patch()
