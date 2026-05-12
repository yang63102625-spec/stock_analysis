# -*- coding: utf-8 -*-
"""Concurrency smoke tests for the lock-protected globals introduced in T4.3."""
from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from bot.dispatcher import RateLimiter
from data_provider.realtime_types import CircuitBreaker


class CircuitBreakerThreadSafetyTest(unittest.TestCase):
    """Hammer the breaker from many threads and assert no exceptions
    leak and the post-state is internally consistent."""

    def test_concurrent_record_failure_does_not_corrupt_state(self) -> None:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
        errors: list[BaseException] = []

        def worker(source: str) -> None:
            try:
                for _ in range(200):
                    breaker.record_failure(source, "boom")
                    breaker.is_available(source)
            except BaseException as exc:  # pragma: no cover - defensive
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            for _ in range(8):
                pool.submit(worker, "src-A")
                pool.submit(worker, "src-B")

        self.assertEqual(errors, [])
        # Every src-A / src-B failure was recorded; both should have
        # tripped to OPEN well past the threshold.
        status = breaker.get_status()
        self.assertEqual(status["src-A"], CircuitBreaker.OPEN)
        self.assertEqual(status["src-B"], CircuitBreaker.OPEN)

    def test_record_success_resets_after_concurrent_failures(self) -> None:
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
        for _ in range(5):
            breaker.record_failure("src", "x")
        self.assertEqual(breaker.get_status()["src"], CircuitBreaker.OPEN)
        breaker.record_success("src")
        self.assertEqual(breaker.get_status()["src"], CircuitBreaker.CLOSED)


class RateLimiterThreadSafetyTest(unittest.TestCase):
    """Bot platforms call ``is_allowed`` from a freshly spawned thread per
    inbound message. Ensure the global cap holds under concurrency."""

    def test_concurrent_is_allowed_caps_at_max_requests(self) -> None:
        limiter = RateLimiter(max_requests=50, window_seconds=60)
        granted = 0
        granted_lock = threading.Lock()

        def worker() -> None:
            nonlocal granted
            for _ in range(20):
                if limiter.is_allowed("user-1"):
                    with granted_lock:
                        granted += 1

        with ThreadPoolExecutor(max_workers=10) as pool:
            for _ in range(10):
                pool.submit(worker)

        # 200 attempts, cap = 50.
        self.assertEqual(granted, 50)
        self.assertEqual(limiter.get_remaining("user-1"), 0)

    def test_window_expiry_releases_quota(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        self.assertTrue(limiter.is_allowed("u"))
        self.assertTrue(limiter.is_allowed("u"))
        self.assertFalse(limiter.is_allowed("u"))
        time.sleep(1.1)
        self.assertTrue(limiter.is_allowed("u"))


if __name__ == "__main__":
    unittest.main()
