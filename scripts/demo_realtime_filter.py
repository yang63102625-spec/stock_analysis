#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick test script for real-time filtering feature.
Demonstrates how the new Stage 1.5 works without running the full pipeline.
"""

import os
from dataclasses import dataclass
from typing import List

# Mock the ScreenedStock class for testing
@dataclass
class MockScreenedStock:
    code: str
    name: str
    change_pct: float
    volume_ratio: float

def test_realtime_filter():
    """Demo of real-time filtering logic."""
    
    # Mock candidates after quantitative screening
    candidates = [
        MockScreenedStock("600519", "贵州茅台", change_pct=2.5, volume_ratio=1.2),
        MockScreenedStock("300750", "宁德时代", change_pct=9.8, volume_ratio=3.5),  # Over limit
        MockScreenedStock("002594", "比亚迪", change_pct=5.2, volume_ratio=6.5),  # High volume
        MockScreenedStock("688008", "澜起科技", change_pct=-10.5, volume_ratio=2.0),  # Limit down
        MockScreenedStock("600000", "浦发银行", change_pct=0.5, volume_ratio=0.8),
        MockScreenedStock("601318", "中国平安", change_pct=10.2, volume_ratio=1.5),  # Limit up
    ]
    
    print("=" * 70)
    print("Real-time Filtering Demo")
    print("=" * 70)
    print(f"\nInitial candidates: {len(candidates)}\n")
    
    for stock in candidates:
        print(f"  {stock.code:>6} {stock.name:>8} | Change: {stock.change_pct:>6.1f}% | Volume Ratio: {stock.volume_ratio:>4.1f}")
    
    print("\n" + "-" * 70)
    print("Filtering Rules (from .env):")
    print("  - PICKER_REALTIME_EXCLUDE_LIMIT_UP = true")
    print("  - PICKER_REALTIME_EXCLUDE_LIMIT_DOWN = true")
    print("  - PICKER_REALTIME_DAILY_CHG_MIN = -2%")
    print("  - PICKER_REALTIME_DAILY_CHG_MAX = 8%")
    print("  - PICKER_REALTIME_MAX_VOLUME_RATIO = 5.0")
    print("-" * 70 + "\n")
    
    # Simulate filtering
    excluded = []
    filtered = []
    
    for stock in candidates:
        reasons = []
        
        # Rule: exclude limit-up (>= 9.5%)
        if stock.change_pct >= 9.5:
            reasons.append(f"涨停({stock.change_pct:.1f}%)")
        
        # Rule: exclude limit-down (<= -9.5%)
        if stock.change_pct <= -9.5:
            reasons.append(f"跌停({stock.change_pct:.1f}%)")
        
        # Rule: daily change range
        if stock.change_pct < -2.0:
            reasons.append(f"涨幅不足(要求>-2%,当前{stock.change_pct:.1f}%)")
        if stock.change_pct > 8.0:
            reasons.append(f"涨幅过大(要求<8%,当前{stock.change_pct:.1f}%)")
        
        # Rule: volume ratio
        if stock.volume_ratio > 5.0:
            reasons.append(f"异常放量(量比{stock.volume_ratio:.1f}>5.0)")
        
        if reasons:
            excluded.append((stock, reasons))
        else:
            filtered.append(stock)
    
    print("Filtering Results:\n")
    print(f"Excluded: {len(excluded)}")
    for stock, reasons in excluded:
        print(f"  ❌ {stock.code:>6} {stock.name:>8} | {', '.join(reasons)}")
    
    print(f"\nPassed: {len(filtered)}")
    for stock in filtered:
        print(f"  ✅ {stock.code:>6} {stock.name:>8} | Change: {stock.change_pct:>6.1f}% | Volume: {stock.volume_ratio:>4.1f}")
    
    print("\n" + "=" * 70)
    print(f"Final result: {len(candidates)} → {len(filtered)} candidates")
    print("=" * 70)

if __name__ == "__main__":
    test_realtime_filter()
