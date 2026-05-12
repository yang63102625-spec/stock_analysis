# -*- coding: utf-8 -*-
"""Shared thread pools and timeout helpers for sync third-party calls."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Callable, Dict, Tuple, TypeVar

T = TypeVar("T")

_TIMEOUT_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="timeout_wrap")

_executor_lock = threading.Lock()
_executor_cache: Dict[Tuple[int, str], ThreadPoolExecutor] = {}


def run_with_timeout(fn: Callable[[], T], timeout: float, label: str = "call") -> T:
    fut = _TIMEOUT_EXECUTOR.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except FuturesTimeout:
        fut.cancel()
        raise


def get_executor(max_workers: int, thread_name_prefix: str) -> ThreadPoolExecutor:
    key = (max_workers, thread_name_prefix)
    with _executor_lock:
        exe = _executor_cache.get(key)
        if exe is None:
            exe = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)
            _executor_cache[key] = exe
        return exe


__all__ = ["FuturesTimeout", "get_executor", "run_with_timeout"]
