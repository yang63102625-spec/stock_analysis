# -*- coding: utf-8 -*-
"""Unified rate limiting and anti-bot protection mixin for data fetchers.

Thread-safety contract
----------------------
``_last_request_time`` and the rate-limit window are tracked **per-instance**
and guarded by an instance-level ``threading.Lock``. The class-level defaults
below act only as fallbacks for subclasses that forget to initialise the
lock/timestamp in ``__init__`` (legacy behaviour).
"""

import logging
import random
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Shared User-Agent pool for rotation across all fetchers.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


class RateLimitMixin:
    """Provides common rate limiting, user-agent rotation, and random sleep.

    Subclasses should set the following instance attributes in ``__init__`` to
    customise behaviour:
        - ``self._rate_limit_min`` (float): minimum interval / sleep seconds
        - ``self._rate_limit_max`` (float): maximum interval / sleep seconds

    Thread safety:
        ``_enforce_rate_limit`` is safe to call from multiple threads sharing
        the same fetcher instance; the wait-and-stamp section is serialised by
        an instance-level lock created lazily on first use.
    """

    # Class-level defaults; instance attributes shadow these.
    _rate_limit_min: float = 2.0
    _rate_limit_max: float = 5.0

    def _get_rate_limit_lock(self) -> threading.Lock:
        """Lazily create a per-instance lock.

        Using a lazy initialiser avoids forcing every subclass to call
        ``super().__init__()`` purely for thread-safety bookkeeping.
        """
        lock = self.__dict__.get("_rate_limit_lock")
        if lock is None:
            # Double-check under the class lock to avoid two threads creating
            # two distinct instance locks during a race.
            if not hasattr(RateLimitMixin, '_rate_limit_class_lock'):
                setattr(RateLimitMixin, '_rate_limit_class_lock', threading.Lock())
            cls_lock = getattr(RateLimitMixin, '_rate_limit_class_lock')
            with cls_lock:
                lock = self.__dict__.get("_rate_limit_lock")
                if lock is None:
                    lock = threading.Lock()
                    self.__dict__["_rate_limit_lock"] = lock
        return lock

    def _enforce_rate_limit(self, min_interval: float = None, max_interval: float = None) -> None:
        """Enforce minimum interval between requests.

        Strategy:
            1. Acquire instance lock.
            2. Sleep the remaining gap (if any) since the last stamped request.
            3. Apply random jitter sleep on top.
            4. Stamp the new ``_last_request_time``.

        Args:
            min_interval: Override minimum sleep (defaults to ``self._rate_limit_min``).
            max_interval: Override maximum sleep (defaults to ``self._rate_limit_max``).
        """
        min_iv = min_interval if min_interval is not None else self._rate_limit_min
        max_iv = max_interval if max_interval is not None else self._rate_limit_max

        with self._get_rate_limit_lock():
            last_ts: Optional[float] = self.__dict__.get("_last_request_time")
            if last_ts is not None:
                elapsed = time.time() - last_ts
                if elapsed < min_iv:
                    additional_sleep = min_iv - elapsed
                    logger.debug(f"Rate limit: sleeping additional {additional_sleep:.2f}s")
                    time.sleep(additional_sleep)

            # Random jitter sleep (still inside the lock so concurrent callers
            # serialise — that is the intended contract for anti-crawl).
            sleep_time = random.uniform(min_iv, max_iv)
            logger.debug(f"Random sleep {sleep_time:.2f}s...")
            time.sleep(sleep_time)
            self.__dict__["_last_request_time"] = time.time()

    def _set_random_user_agent(self) -> None:
        """Rotate User-Agent header to avoid detection.

        Currently logs the selected UA at debug level. Subclasses may override
        to inject the UA into a session/headers dict.
        """
        try:
            random_ua = random.choice(USER_AGENTS)
            logger.debug(f"User-Agent set: {random_ua[:50]}...")
        except Exception as e:  # noqa: BLE001  -- defensive: never break callers
            logger.debug(f"Failed to set User-Agent: {e}")

    def _random_sleep(self, min_seconds: float = None, max_seconds: float = None) -> None:
        """Sleep for a random duration between requests (no rate-window stamping).

        Args:
            min_seconds: Minimum sleep time (defaults to ``self._rate_limit_min``).
            max_seconds: Maximum sleep time (defaults to ``self._rate_limit_max``).
        """
        lo = min_seconds if min_seconds is not None else self._rate_limit_min
        hi = max_seconds if max_seconds is not None else self._rate_limit_max
        sleep_time = random.uniform(lo, hi)
        logger.debug(f"Random sleep {sleep_time:.2f}s...")
        time.sleep(sleep_time)
