# -*- coding: utf-8 -*-
"""Score-effectiveness analysis mixin for ``BacktestService``.

Extracted from ``backtest_service.py`` to keep that module under the
800-line ceiling (rule §1). The mixin only needs ``self.db`` (a
``DatabaseManager``) which is provided by the host class.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from src.storage import AnalysisHistory, BacktestResult, DatabaseManager


class _ScoreEffectivenessMixin:
    """Score effectiveness analysis (correlation + bucket breakdown).

    The mixin assumes the host class exposes ``self.db: DatabaseManager``.
    Method signatures are unchanged from the previous monolithic
    ``BacktestService`` implementation.
    """

    db: DatabaseManager  # provided by the host class

    def analyze_score_effectiveness(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        eval_window_days: int = 5,
        score_bucket_size: int = 10,
    ) -> Dict[str, Any]:
        """
        Analyze correlation between sentiment scores and actual returns.

        Groups completed backtest results by score bucket and calculates
        win rate, average return, and other metrics for each bucket.

        Returns:
            {
                'total_samples': int,
                'buckets': [...],
                'correlation': float,
                'conclusion': str,
            }
        """
        with self.db.get_session() as session:
            query = (
                select(
                    AnalysisHistory.sentiment_score,
                    AnalysisHistory.trend_score,
                    AnalysisHistory.bias_score,
                    AnalysisHistory.volume_score,
                    AnalysisHistory.support_score,
                    AnalysisHistory.macd_score,
                    AnalysisHistory.rsi_score,
                    AnalysisHistory.capital_flow_score,
                    BacktestResult.stock_return_pct,
                    BacktestResult.simulated_return_pct,
                    BacktestResult.outcome,
                    BacktestResult.min_low,
                    BacktestResult.start_price,
                )
                .join(BacktestResult, BacktestResult.analysis_history_id == AnalysisHistory.id)
                .where(BacktestResult.eval_status == "completed")
            )

            if start_date:
                query = query.where(
                    AnalysisHistory.created_at >= datetime.strptime(start_date, "%Y-%m-%d")
                )
            if end_date:
                query = query.where(
                    AnalysisHistory.created_at
                    < datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                )
            if eval_window_days:
                query = query.where(BacktestResult.eval_window_days == eval_window_days)

            rows = session.execute(query).all()

        if not rows:
            return {
                "total_samples": 0,
                "buckets": [],
                "correlation": 0.0,
                "conclusion": "No completed backtest data available for analysis.",
            }

        scores: List[float] = []
        returns: List[float] = []
        buckets_data: Dict[int, List[Dict[str, Any]]] = {}

        for row in rows:
            sentiment = row.sentiment_score
            if sentiment is None:
                continue
            stock_return = row.stock_return_pct
            if stock_return is None:
                continue

            scores.append(float(sentiment))
            returns.append(float(stock_return))

            bucket_key = (int(sentiment) // score_bucket_size) * score_bucket_size
            if bucket_key not in buckets_data:
                buckets_data[bucket_key] = []

            max_drawdown = 0.0
            if row.start_price and row.min_low and row.start_price > 0:
                max_drawdown = (
                    (float(row.min_low) - float(row.start_price)) / float(row.start_price) * 100
                )

            buckets_data[bucket_key].append({
                "return_pct": float(stock_return),
                "simulated_return_pct": float(row.simulated_return_pct) if row.simulated_return_pct else 0.0,
                "outcome": row.outcome,
                "max_drawdown_pct": max_drawdown,
            })

        bucket_results = []
        for bucket_key in sorted(buckets_data.keys()):
            items = buckets_data[bucket_key]
            count = len(items)
            wins = sum(1 for i in items if i["outcome"] == "win")
            avg_return = sum(i["return_pct"] for i in items) / count
            avg_sim_return = sum(i["simulated_return_pct"] for i in items) / count
            max_dd = min(i["max_drawdown_pct"] for i in items) if items else 0.0

            bucket_results.append({
                "range": f"{bucket_key}-{bucket_key + score_bucket_size}",
                "count": count,
                "win_rate": round(wins / count * 100, 1) if count else 0.0,
                "avg_return_pct": round(avg_return, 2),
                "max_drawdown_pct": round(max_dd, 2),
                "avg_simulated_return_pct": round(avg_sim_return, 2),
            })

        correlation = self._pearson_correlation(scores, returns)
        conclusion = self._generate_score_conclusion(correlation, bucket_results, len(scores))

        return {
            "total_samples": len(scores),
            "buckets": bucket_results,
            "correlation": round(correlation, 4),
            "conclusion": conclusion,
        }

    @staticmethod
    def _pearson_correlation(x: List[float], y: List[float]) -> float:
        """Compute Pearson correlation coefficient between two lists."""
        n = len(x)
        if n < 3:
            return 0.0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
        if std_x == 0 or std_y == 0:
            return 0.0
        return cov / (std_x * std_y)

    @staticmethod
    def _generate_score_conclusion(correlation: float, buckets: List[Dict], total: int) -> str:
        """Generate a human-readable conclusion about score effectiveness."""
        if total < 10:
            return (
                f"Insufficient data ({total} samples). "
                "Need at least 10 completed backtests for meaningful analysis."
            )

        strength = abs(correlation)
        if strength >= 0.7:
            quality = "strong"
        elif strength >= 0.4:
            quality = "moderate"
        elif strength >= 0.2:
            quality = "weak"
        else:
            quality = "negligible"

        direction = "positive" if correlation > 0 else "negative"
        if quality == "negligible":
            direction_text = ""
        else:
            direction_text = f" {direction}"

        if buckets:
            best = max(buckets, key=lambda b: b["avg_return_pct"])
            worst = min(buckets, key=lambda b: b["avg_return_pct"])
            bucket_info = (
                f" Best performing bucket: {best['range']} "
                f"(avg return {best['avg_return_pct']}%, win rate {best['win_rate']}%). "
                f"Worst: {worst['range']} (avg return {worst['avg_return_pct']}%)."
            )
        else:
            bucket_info = ""

        return (
            f"Score-return correlation is {quality}{direction_text} "
            f"(r={correlation:.3f}, n={total}).{bucket_info}"
        )
