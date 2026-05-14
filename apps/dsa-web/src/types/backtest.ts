/**
 * Backtest API type definitions
 * Mirrors api/v1/schemas/backtest.py
 */

// ============ Request / Response ============

export interface BacktestRunRequest {
  code?: string;
  force?: boolean;
  evalWindowDays?: number;
  minAgeDays?: number;
  limit?: number;
}

export interface BacktestRunResponse {
  processed: number;
  saved: number;
  completed: number;
  insufficient: number;
  errors: number;
}

// ============ Result Item ============

export interface BacktestResultItem {
  analysisHistoryId: number;
  code: string;
  name?: string;
  analysisDate?: string;
  evalWindowDays: number;
  evalStatus: string;
  evaluatedAt?: string;
  operationAdvice?: string;
  positionRecommendation?: string;
  startPrice?: number;
  endClose?: number;
  maxHigh?: number;
  minLow?: number;
  stockReturnPct?: number;
  directionExpected?: string;
  directionCorrect?: boolean;
  outcome?: string;
  stopLoss?: number;
  takeProfit?: number;
  hitStopLoss?: boolean;
  hitTakeProfit?: boolean;
  firstHit?: string;
  firstHitDate?: string;
  firstHitTradingDays?: number;
  simulatedEntryPrice?: number;
  simulatedExitPrice?: number;
  simulatedExitReason?: string;
  simulatedReturnPct?: number;
  // v2: System-computed signal snapshot + sim diagnostics
  signalScoreAtEval?: number;
  buySignalAtEval?: string;  // STRONG_BUY/BUY/HOLD/AVOID/STRONG_AVOID
  marketEnvironmentAtEval?: string;
  strategyId?: string;
  riskRewardAtEval?: number;
  positionPctAtEval?: number;
  trendScoreAtEval?: number;
  biasScoreAtEval?: number;
  volumeScoreAtEval?: number;
  supportScoreAtEval?: number;
  macdScoreAtEval?: number;
  rsiScoreAtEval?: number;
  capitalFlowScoreAtEval?: number;
  exitReason?: string;
  holdDays?: number;
  // v3: AI-plan execution
  entryStatus?: string;
  rMultiple?: number;
  maePct?: number;
  mfePct?: number;
}

export interface BacktestResultsResponse {
  total: number;
  page: number;
  limit: number;
  items: BacktestResultItem[];
}

// ============ Performance Metrics ============

export interface PerformanceMetrics {
  scope: string;
  code?: string;
  evalWindowDays: number;
  computedAt?: string;

  totalEvaluations: number;
  completedCount: number;
  insufficientCount: number;
  longCount: number;
  cashCount: number;
  winCount: number;
  lossCount: number;
  neutralCount: number;

  directionAccuracyPct?: number;
  winRatePct?: number;
  neutralRatePct?: number;
  avgStockReturnPct?: number;
  avgSimulatedReturnPct?: number;

  stopLossTriggerRate?: number;
  takeProfitTriggerRate?: number;
  ambiguousRate?: number;
  avgDaysToFirstHit?: number;

  // v3 AI-plan execution metrics
  fillRatePct?: number;
  filledCount: number;
  notFilledCount: number;
  notFilledLimitUpCount: number;
  tradeWinRatePct?: number;
  expectancyPct?: number;
  avgRMultiple?: number;
  profitFactor?: number;
  maxDrawdownPct?: number;
  avgMaePct?: number;
  avgMfePct?: number;
  ambiguousCount: number;

  diagnostics: Record<string, unknown>;
  signalBreakdown?: Record<string, BreakdownBucket>;
  scoreBucketBreakdown?: Record<string, BreakdownBucket>;
  riskRewardBreakdown?: Record<string, BreakdownBucket>;
  exitReasonBreakdown?: Record<string, BreakdownBucket>;
  regimeBreakdown?: Record<string, BreakdownBucket>;
  strategyBreakdown?: Record<string, BreakdownBucket>;
}

export interface BreakdownBucket {
  total: number;
  win: number;
  loss: number;
  neutral: number;
  win_rate_pct?: number | null;
}
