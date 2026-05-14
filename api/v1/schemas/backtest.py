# -*- coding: utf-8 -*-
"""Backtest API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    code: Optional[str] = Field(None, description="仅回测指定股票")
    force: bool = Field(False, description="强制重新计算")
    eval_window_days: Optional[int] = Field(None, ge=1, le=120, description="评估窗口（交易日数）")
    min_age_days: Optional[int] = Field(None, ge=0, le=365, description="分析记录最小天龄（0=不限）")
    limit: int = Field(200, ge=1, le=2000, description="最多处理的分析记录数")
    strategies: Optional[List[str]] = Field(
        None,
        deprecated=True,
        description="Deprecated since v3: backtest now replays each AI plan as-is, no strategy override.",
    )


class BacktestRunResponse(BaseModel):
    processed: int = Field(..., description="候选记录数")
    saved: int = Field(..., description="写入回测结果数")
    completed: int = Field(..., description="完成回测数")
    insufficient: int = Field(..., description="数据不足数")
    errors: int = Field(..., description="错误数")


class BacktestResultItem(BaseModel):
    analysis_history_id: int
    code: str
    name: str = ""
    analysis_date: Optional[str] = None
    eval_window_days: int
    eval_status: str
    evaluated_at: Optional[str] = None
    operation_advice: Optional[str] = None
    position_recommendation: Optional[str] = None
    start_price: Optional[float] = None
    end_close: Optional[float] = None
    max_high: Optional[float] = None
    min_low: Optional[float] = None
    stock_return_pct: Optional[float] = None
    direction_expected: Optional[str] = None
    direction_correct: Optional[bool] = None
    outcome: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    hit_stop_loss: Optional[bool] = None
    hit_take_profit: Optional[bool] = None
    first_hit: Optional[str] = None
    first_hit_date: Optional[str] = None
    first_hit_trading_days: Optional[int] = None
    simulated_entry_price: Optional[float] = None
    simulated_exit_price: Optional[float] = None
    simulated_exit_reason: Optional[str] = None
    simulated_return_pct: Optional[float] = None
    # v2: System-computed signal snapshot + sim diagnostics
    signal_score_at_eval: Optional[int] = None
    buy_signal_at_eval: Optional[str] = None  # STRONG_BUY/BUY/HOLD/AVOID/STRONG_AVOID
    market_environment_at_eval: Optional[str] = None
    strategy_id: Optional[str] = None
    risk_reward_at_eval: Optional[float] = None
    position_pct_at_eval: Optional[float] = None
    trend_score_at_eval: Optional[int] = None
    bias_score_at_eval: Optional[int] = None
    volume_score_at_eval: Optional[int] = None
    support_score_at_eval: Optional[int] = None
    macd_score_at_eval: Optional[int] = None
    rsi_score_at_eval: Optional[int] = None
    capital_flow_score_at_eval: Optional[int] = None
    exit_reason: Optional[str] = None  # stop_loss / take_profit / time_exit / not_filled / not_filled_limit_up / stop_loss_ambiguous / cash
    hold_days: Optional[int] = None
    # v3: AI-plan execution
    entry_status: Optional[str] = None  # filled / not_filled / not_filled_limit_up
    r_multiple: Optional[float] = None
    mae_pct: Optional[float] = None
    mfe_pct: Optional[float] = None


class BacktestResultsResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[BacktestResultItem] = Field(default_factory=list)


class PerformanceMetrics(BaseModel):
    scope: str
    code: Optional[str] = None
    eval_window_days: int
    computed_at: Optional[str] = None

    total_evaluations: int
    completed_count: int
    insufficient_count: int
    long_count: int
    cash_count: int
    win_count: int
    loss_count: int
    neutral_count: int

    direction_accuracy_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    neutral_rate_pct: Optional[float] = None
    avg_stock_return_pct: Optional[float] = None
    avg_simulated_return_pct: Optional[float] = None

    stop_loss_trigger_rate: Optional[float] = None
    take_profit_trigger_rate: Optional[float] = None
    ambiguous_rate: Optional[float] = None
    avg_days_to_first_hit: Optional[float] = None

    # v3: AI-plan execution metrics
    fill_rate_pct: Optional[float] = None
    filled_count: int = 0
    not_filled_count: int = 0
    not_filled_limit_up_count: int = 0
    trade_win_rate_pct: Optional[float] = None
    expectancy_pct: Optional[float] = None
    avg_r_multiple: Optional[float] = None
    profit_factor: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    avg_mae_pct: Optional[float] = None
    avg_mfe_pct: Optional[float] = None
    ambiguous_count: int = 0

    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    signal_breakdown: Dict[str, Any] = Field(default_factory=dict)
    score_bucket_breakdown: Dict[str, Any] = Field(default_factory=dict)
    exit_reason_breakdown: Dict[str, Any] = Field(default_factory=dict)
    regime_breakdown: Dict[str, Any] = Field(default_factory=dict)
    strategy_breakdown: Dict[str, Any] = Field(default_factory=dict)

