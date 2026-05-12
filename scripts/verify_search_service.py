#!/usr/bin/env python3
"""Verification script for the two fixes."""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []

# Test 1: Syntax check for search_service.py
try:
    import py_compile
    py_compile.compile('src/search_service.py', doraise=True)
    results.append("PASS: search_service.py syntax OK")
except py_compile.PyCompileError as e:
    results.append(f"FAIL: search_service.py syntax error: {e}")

# Test 2: Check MiniMaxSearchProvider.is_available
try:
    from src.search_service import MiniMaxSearchProvider
    provider = MiniMaxSearchProvider(['test_key'])
    # Check that is_available returns True when keys are configured and circuit breaker is not open
    if provider.is_available:
        results.append("PASS: MiniMaxSearchProvider.is_available returns True (circuit breaker logic restored)")
    else:
        results.append("FAIL: MiniMaxSearchProvider.is_available returns False unexpectedly")
except Exception as e:
    results.append(f"FAIL: MiniMaxSearchProvider test error: {e}")

# Test 3: Check config parsing
try:
    from src.config import get_config
    config = get_config()
    results.append(f"PASS: Config loaded, model={config.litellm_model}")
    results.append(f"INFO: LLM channels count={len(config.llm_channels)}")
    if config.llm_channels:
        for ch in config.llm_channels:
            results.append(f"  Channel: {ch.get('name')}, models={ch.get('models')}")
except Exception as e:
    results.append(f"FAIL: Config load error: {e}")

# Test 4: Check SearchService providers
try:
    from src.search_service import get_search_service
    s = get_search_service()
    results.append(f"INFO: Search service available={s.is_available}")
    for p in s._providers:
        results.append(f"  Provider: {p.name}, available={p.is_available}")
except Exception as e:
    results.append(f"FAIL: SearchService test error: {e}")

# Write results to file in project directory
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verification_results.txt')
with open(output_path, 'w') as f:
    for r in results:
        f.write(r + '\n')
        print(r)
