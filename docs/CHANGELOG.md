# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/jiasanpang/stock_analysis/releases) page.

## [Unreleased]

### Changed (Parameter Tuning Wave — Investment-Expert Review)
- **R/R floor raised 1.8 → 2.0** (`trade_levels.RR_MIN`): A-share round-trip cost (slippage + tax) ~0.5% leaves net 1.5 at 1.8 — insufficient at <50% win rate. New 2.0 keeps positive expectancy at win rates ≥45%.
- **Trailing trigger lowered +20% → +15%** (`evaluate_trailing_exit`): A-share rallies often start ABC consolidation around +18-22%; entering trailing at +15% locks 3-5% additional profit on average.
- **Stage stops widened**: 5% / 10% → 6% / 12% to reduce premature stop-outs from intraday noise. New floor at +6% break.
- **Position baselines tightened** (`_base_position_pct`): small-cap 6% → 5%, large-cap 18% → 15% to cap single-name idiosyncratic blow-ups; mid-cap unchanged at 12%.
- **Position boost re-shaped**: R/R≥3 boost 1.20×→1.30×, absolute cap 25%→22% — separates "great" signals from "decent" ones while keeping single-name exposure safer.
- **Small-cap stop loosened** -5% → -6%: small caps need wider stops vs intraday noise.
- **Breakout tp1 1.06 → 1.08**: first-leg average is +8-12%; trimming at +6% truncated fat-tail winners.
- **Bottom-reversal hard cap +15% → +20%** with new staged exit (+15% trim half, +20% full clear): real reversals run +18-25% on main leg; +15 single-shot capped winners.
- **EOD buyback `expected_mult` 1.025 → 1.018**: aligns with realistic next-day median return; previous value inflated R/R and over-sized position.
- **Picker filters tightened**:
  - `BUY_PULLBACK.change_60d_min` 5% → 8%
  - `BREAKOUT.volume_ratio_min` 2.0 → 1.7 (eased; 2.0 over-filtered moderate-volume genuine breakouts)
  - `BOTTOM_REVERSAL.change_60d_max` -5% → -8%
  - B-wave fib zone 0.35-0.65 → exact 0.382-0.618
- **Resonance bonus re-shaped**: double +10 → +8, triple +20 → +25 (widen gap; triple resonance is rare and historically much higher win rate).
- **Auto-reweight stricter**: lookback 28d → 42d (covers ≥1 style-rotation cycle), bad win-rate floor 40% → 42%, penalty factor 0.7 → 0.6 (more decisive).
- **Veto thresholds tightened**: pledge ratio 60% → 50% (most A-share pledge blow-ups occur >50%), reduction window 5d/2% → 10d/1% (insider-selling impact persists 2-3 weeks).
- **Regime-aware position scaling (E1)**: weak market ×0.6, neutral ×0.85, strong ×1.0 applied post-merge in `stock_picker_service.screen()` — complements existing market_guard which only restricts strategies.

### Refactored
- `trade_levels.py`: collapsed 4 strategy-specific level-builder functions into a single config-table-driven implementation (`_StrategyConfig` + `_resolve_entry_anchor`). Removes ~120 lines of duplicate code; new strategies / parameter tuning now require config-only changes.

### Changed (Scoring Dimension Rebalance — Remove MA5-support Redundancy)
- **Support dimension 12 → 6**: removed MA5-support (structurally redundant with `bias_ma5` dimension — both measure "close to MA5"; old setup triple-counted "healthy pullback" theme as bias 14 + volume 18 + ma5_support 7 = 40% of total on one signal cluster). Kept MA10-support at 5; added MA20 trend-integrity at 1 (price above rising MA20).
- **MACD 10 → 13**: re-allocated from support; MACD is genuinely independent alpha but was under-weighted. Smoother ladder (GOLDEN_CROSS_ZERO 13 → BULLISH 8).
- **Capital flow 10 → 13**: re-allocated from support. External-facing `capital_flow_score` contract stays 0-10 (no upstream change needed); internal contribution is `raw × 1.3`.
- New dimension shape: Trend 30 / Bias 15 / Volume 18 / Support 6 / MACD 13 / RSI 5 / CapitalFlow 13 = 100.

### Changed (Per-stock Scoring System Hardening — 8 fixes)
- **Regime-aware classifier** (`classify_buy_signal`): bear / strong_bear bump BUY/STRONG_BUY thresholds by +10 (60→70, 75→85) so a "looks good" 60-score in bear no longer triggers BUY.
- **Hard score caps by market regime** (`_generate_signal`): strong_bear ×0.85→×0.75 with absolute cap 60; bear ×0.90→×0.85 with cap 75 — defense-in-depth against false-positive BUY signals in down markets.
- **PE valuation penalty**: PE>100 -8, PE>200 -15, PE<0 (loss) -5 — closes the bubble-stock loophole where 100x-PE names could still score 80+. New `TrendAnalysisResult.pe_ratio` field (optional, 0=skip).
- **Capital flow score clip**: `[0, 10]` clamp guards against external sources returning out-of-range values that silently inflated total score.
- **HEAVY_VOLUME_UP demotion in late-acceleration**: when 20d gain >30% or 5+ consecutive up days, score 14→6 (放量上涨 in 加速期 is typically distribution).
- **SHRINK_VOLUME_UP demotion in strong/bull trends**: 7→3 (滞涨缩量 = top divergence in uptrends).
- **MACD ladder smoothing**: CROSSING_UP 7→8, BULLISH 5→6 — closes the gap between strongest signal and persistent-bullish.
- **Bias dead-zone fix**: when MA20 history unavailable for `bias < -5` branch, replace flat 6 with linear interpolation of bias magnitude (avoids step discontinuity).

### Added
- **Unified trade levels engine** (`src/services/trade_levels.py`): single source of truth for entry / stop-loss / take-profit / position size / risk-reward across picker, analyzer, and backtest layers. Strategy-aware (buy_pullback / breakout / bottom_reversal / eod_buyback) with ATR-based trailing stop replacing fixed 15% take-profit ceiling for trend strategies — lets winners run on strong trends.
- **Trailing stop logic** (`evaluate_trailing_exit`): after +20% profit, exit on MA10 break OR ATR×2.5 retrace from peak. Bottom-reversal keeps hard +15% cap (no trailing). Stage-aware exits at +5% (trim 1/3, stop to cost) and +10% (trim again, stop to +5%).
- **Position tracker service** (`src/services/position_tracker.py`): stateless API for evaluating any held position against unified trailing rules, returning structured action recommendations. Ready for integration into watchlist scans / agent skills.
- **Picker outputs trade levels**: `ScreenedStock` and `StockPick` now carry `ideal_buy / stop_loss / take_profit_1 / take_profit_2_rule / position_pct / risk_reward`. Notifications and AI-selection prompts display these fields so users have immediate trade-action clarity.
- **Risk/Reward hard filter**: candidates with R/R < 1.8 are dropped during scoring. R/R is computed against an "expected average exit" (12-13% for trend strategies, 11.5% for reversal, 2.5% for EOD) that accounts for staged trimming + trailing tail.
- **Multi-strategy resonance bonus**: stocks flagged by 2 strategies get +10 score and `resonance="double"`; 3+ strategies get +20 and `resonance="triple"` (forced inclusion in AI selection prompt with ⭐⭐⭐ badge).
- **Fundamental hard-veto filter** (`data_provider/fundamentals_fetcher.py`): pre-screening removes candidates with controlling-shareholder pledge >60%, goodwill/total-assets >30%, recent ≥2% holder reductions, or negative earnings forecasts (预亏/预减/首亏/续亏/增亏). Fail-closed when Tushare unavailable. Filter stats recorded in `ScreenStats.veto_reasons`.
- **Strategy attribution service** (`src/services/strategy_attribution_service.py`): rolling 4-week per-strategy win-rate / profit-factor / max-drawdown computed from historical picker_history, with auto-reweighting (×0.7) for strategies that hit BOTH win-rate <40% AND profit-factor <1. Off by default (`STRATEGY_AUTO_REWEIGHT=true` to enable). Includes weekly report formatter.
- **Backtest unified with production**: `picker_backtest_service._get_forward_return` now uses the same trade_levels exit rules + 0.3% slippage + limit-up entry filter, eliminating the previous three-way rule mismatch (picker/analyzer/backtest).
- **Trade levels in analyzer prompt**: `_enhance_context` injects pre-computed `trade_levels` block; SYSTEM_PROMPT instructs LLM to use these numbers directly rather than inventing its own — addresses recurring stop/take confusion bugs.
- Seven-dimension scoring system (trend 30 + bias 15 + volume 18 + support 12 + MACD 10 + RSI 5 + capital flow 10 = 100)
- Market environment correction factor based on SSE MA20 direction (strong_bear ×0.85, bear ×0.90, neutral/bull ×1.0, strong_bull ×1.05)
- Phase-based bias threshold (startup 6%, main-rise 5%, acceleration 3.5%)
- ATR(20) dynamic bias threshold adjustment with local fallback calculation
- Capital flow scoring via Tushare moneyflow (main force + northbound, min 1M threshold)
- Stop-loss/take-profit consistency constraints in LLM prompts
- Dimension scores persistence for backtest evaluation in Agent mode
- Unified buy signal classification via `StockTrendAnalyzer.classify_buy_signal()`

### Fixed
- Agent mode missing dimension scores causing all backtest results to show "negative"
- DataFetcherManager thread-safety issue (double-checked locking in both __new__ and __init__)
- ATR_20 dynamic threshold never effective in production (DB didn't store the column)
- Prompt principle #7 contradicting code logic (updated to phase-based rule)
- Volume shrinkage scoring now market-condition-aware (bull 18 / sideways 10 / bear 0)

### Changed
- Bias threshold from fixed 4.5% to phase-based (3.5% / 5.0% / 6.0%)
- Strong bear market coefficient from 0.75 to 0.85
- Bear market coefficient from 0.85 to 0.90
- Volume exhaustion penalty: -5 points; extreme volume warning: -15 points
- Capital flow scoring tightened (6/3/1/0 for main force, 4/2/1/0 for northbound)

### Removed
- 17 deprecated Optional fields from AnalysisReportSchema (old format)
- `sector_relative_strength` unused field from TrendAnalysisResult
- All legacy analysis history data (database cleanup)

### Enhanced
- **个股分析评分体系重构** — 新增资金面维度(10分)，调整权重配比（降低MACD/RSI滞后指标权重，提升量能/支撑位权重）
- **动态乖离率阈值** — 基于20日ATR波动率自适应调整（高波动股放宽、低波动股收紧）
- **RSI超卖企稳条件** — RSI<30需连续2日回升确认企稳才给满分，避免下跌趋势误判
- **乖离率MA20方向区分** — 负乖离率时区分MA20上行(超跌反弹)与MA20下行(趋势破坏)
- **多日量能趋势分析** — 新增3/10/20日均量对比、天量预警(>5倍)、量能衰竭检测
- **资金面数据接入** — 接入Tushare北向资金(moneyflow_hsgt)和个股主力资金(moneyflow)，纳入评分体系
- **LLM Prompt增强** — 新增止盈止损规则、量能深度解读指令、资金面三角验证逻辑

### Added
- `data_provider/moneyflow_fetcher.py` — 资金流向数据获取模块(MoneyflowFetcher)
- Agent工具 `get_capital_flow` — 个股资金面分析工具

### Performance
- **perf(sector)**: Background preload of sector ranking & member data at startup via FastAPI lifespan
- **perf(sector)**: Periodic background refresh every 50 minutes (before 1-hour cache TTL)
- **perf(sector)**: Class-level shared cache across all service instances (preloaded data reusable by requests)
- **perf(sector)**: Concurrent member fetch with 10 workers and 300s timeout

### Fixed
- **fix(sector)**: Correct `TimeoutError` type for `concurrent.futures.as_completed` (`FuturesTimeout`)
- **fix(sector)**: Thread-safe cache reads with `_cache_lock`
- **fix(sector)**: Preload moved from `server.py` to `api/app.py` lifespan to work with all startup methods
- **fix(ci)**: Add `LLM_MINIMAX_*` env vars to `daily_analysis.yml` workflow

### Improved
- **improve(sector)**: AkShare retry logic (3 attempts with 5/10/15s backoff) for flaky East Money API
- **improve(picker)**: 180s timeout wrapper for sector code fetch with graceful degradation

### Added
- **feat(picker)**: 板块强度过滤 — 选股前自动过滤弱势板块，仅从强势行业板块成分股中选股
  - 按策略区分：buy_pullback/breakout 启用，bottom_reversal 跳过
  - 新增 `SectorStrengthService` 提供板块排名和成分股获取（AkShare数据源）
  - 新增环境变量：`PICKER_SECTOR_FILTER`, `PICKER_SECTOR_TOP_PCT`
- **feat(picker)**: MarketGuard 市场环境开关 — 沪指低于MA20超1%时自动限制选股策略
  - 三档判断：strong / neutral（缓冲区0~1%）/ weak
  - 新增 `get_index_daily_data()` 正确获取上证指数日线数据
  - 新增环境变量：`PICKER_MARKET_GUARD`, `PICKER_WEAK_MARKET_ACTION`, `PICKER_WEAK_MARKET_STRATEGIES`
- **feat(picker)**: buy_pullback 新增距20日高点最小距离过滤 (`min_pullback_from_high_pct=3.0`)，排除追高
- **feat(picker)**: buy_pullback 新增 MA20 下跌通道防护 (`require_price_above_ma20`)，跌破 MA20 排除
- **feat(picker)**: buy_pullback 新增 MA10 支撑位距离过滤 (`max_distance_above_ma10_pct=3.0`)，确认支撑位附近
- **feat(picker)**: eod_buyback 策略重写为龙虾方案 — 使用 `ts.get_realtime_quotes()` 分批200只查询全市场实时行情，替代 efinance 全市场接口
- **feat(picker)**: eod_buyback 补充 Tushare Pro `daily_basic` 数据（换手率、总市值）
- **feat(picker)**: eod_buyback 添加盘后量比过滤（15:00后生效）和 VWAP 实时验证

### Fixed
- **fix(picker)**: 修复 `_filter_by_realtime()` NoneType 比较崩溃，添加 `_safe_float()` 防护
- **fix(picker)**: eod_buyback 候选完整 bypass `_filter_by_realtime()`，避免双重过滤
- **fix(data)**: 修复 Tushare `change_amount` 计算错误（`bid-ask` → `price-pre_close`）
- **fix(data)**: 修复 Tushare 实时行情 9 个字段硬编码 0.0 改为 None
- **fix(picker)**: 空筛选池三重防护 — 跳过LLM、后验证、提示词加严
- **fix(picker)**: MarketGuard 指数代码 bug — `get_daily_data("000001")` 返回平安银行而非上证指数
- **fix(picker)**: MarketGuard limit 模式永久修改策略列表 — 改用 try/finally 恢复原始策略

### Changed
- **refactor(picker)**: buy_pullback 策略参数优化 — 均线多头加0.5%容差，缩量条件放宽至1.3
- **refactor(picker)**: buy_pullback 评分函数重写 — 量比评分奖励缩量，动量评分对齐入池范围
- **refactor(picker)**: buy_pullback 策略参数全面收紧 — 启用缩量检查、量比0.7、乖离率5%、PE上限60、日涨幅上限2%、60日上限40%、回调限制0.4
- **refactor(picker)**: buy_pullback 评分优化 — 缩量(0.5-0.9)最高分、深回踩(-3%~-1%)最高分、放量(>3.0)惩罚
- **refactor(picker)**: 底部反转策略参数优化 — 启用缩量检查、量比0.7、60日上限-5%、B浪过滤0.618
- **refactor(picker)**: 底部反转评分增强 — 60日跌幅深度加分、缩量→放量转折信号、反转K线形态加分
- **refactor(picker)**: bottom_reversal `daily_change_min` 0.0→1.0，实时验证更严格
- **refactor(picker)**: 清理未使用的全市场实时路径死代码（fetch_realtime_market_data、get_realtime_all_spots）
- **refactor(picker)**: 删除重复的 `_has_recent_limit_up` 函数
- **perf**: 并发超时 10s→60s，eastmoney patch 超时 15s→30s

### Added (previous)
- Real-time filtering stage (Stage 1.5) for stock picker: After quantitative screening, filter candidates by live market conditions (limit-up/down, daily price range, volume spike). **Enables intraday picking & same-day trading**.
  - `PICKER_ENABLE_REALTIME_FILTER` (bool, default true): Main toggle
  - `PICKER_REALTIME_EXCLUDE_LIMIT_UP` (bool, default true): Exclude up-limit-locked stocks
  - `PICKER_REALTIME_EXCLUDE_LIMIT_DOWN` (bool, default true): Exclude down-limit-locked stocks
  - `PICKER_REALTIME_DAILY_CHG_MIN` (float, optional): Min daily gain % (e.g. -2 for at least -2% pullback)
  - `PICKER_REALTIME_DAILY_CHG_MAX` (float, optional): Max daily gain % (e.g. 8 to avoid chasing too high)
  - `PICKER_REALTIME_MAX_VOLUME_RATIO` (float, default 0): Filter abnormal volume spikes (0 = no limit)
- New guide: `docs/realtime-picker-guide.md` with 3 ready-to-use templates (conservative/balanced/aggressive)
- Demo script: `test_realtime_filter_demo.py` shows filtering logic in action

### Changed
- Picker pipeline now has 3 stages:
  1. Quantitative screening (historical daily data)
  2. **Real-time filtering** (NEW: intraday market conditions)
  3. AI selection (LLM picks 1-5 from filtered pool)

### Picker page: Pill-style strategy chips (buy_pullback, breakout, bottom_reversal), card container, result view shows strategy + timestamp.
- Picker backtest: Strategy selection (replaces mode dropdown). API accepts `picker_strategies`; history stores `picker_strategies_json`.
- Per-strategy leader bias exemption: `leader_bias_exempt_pct` in StrategyParams (breakout=14%, others=0). Removed global `PICKER_LEADER_BIAS_EXEMPT_PCT`.

### Changed
- GitHub Actions `daily_analysis.yml`: default schedule Beijing 18:00 (`cron`: UTC 10:00 Mon–Fri).
- Picker backtest: Remove `picker_mode` and `picker_leader_bias_exempt_pct` from API. Use `picker_strategies` only.
- Backtest page: holdDays/topN inputs allow empty (string state, parse on submit).
- Picker footer tagline: "买回踩 · 突破 · 底部反转 — 多策略并行，按需组合".

### Removed
- `PICKER_LEADER_BIAS_EXEMPT_PCT` env var (leader exemption now per-strategy).
- Picker mode (严进/平衡/进攻) from picker backtest API and UI.

### Added (previous)
- Multi-strategy picker: `PICKER_STRATEGIES` (comma-separated) runs multiple strategies in parallel. Strategies: `buy_pullback` (买回踩), `breakout` (突破), `bottom_reversal` (底部反转). Candidates merged and tagged by strategy. No intensity modes (defensive/balanced/offensive) — each strategy has fixed params.
- Picker strategy comparison view: API returns `screened_pool_by_strategy` (per-strategy candidate lists). Frontend toggle "合并" / "按策略对比" to view merged pool or each strategy's candidates separately for comparison.

### Changed
- Picker strategy params (expert-tuned): 买回踩 daily_change -2.5%~3% (was -1%~4%), pe_ideal_high 35 (was 30); 底部反转 max_retracement_pct 1.0 (was 0.618), pe_max 100 (was 80); MACD max_retracement_pct 0.8 (was 0.618).
- Picker basic filter: Remove low-price filter (was exclude price < 3 yuan). Low-priced stocks are no longer excluded.
- Sector rankings (板块排行): Tushare `sw_daily` as priority source when TUSHARE_TOKEN configured. Avoids Eastmoney rate limiting (RemoteDisconnected). Requires 5000+ Tushare points.
- Picker backtest: stop-loss/take-profit per 买卖点规则 — stop-loss: 跌破 MA20 or -8% drawdown; take-profit: 前高 (20d high), 整数关口 (5/10/20/50/100...), or +15% fallback.
- Picker backtest speed: `CachingDataFetcherManager` caches get_daily_data per run; screener filters (`_filter_by_bias`, `_filter_limit_up_streak`, `_filter_consecutive_up_days`, `_filter_b_wave_risk`) fetch in parallel (5 workers) with request deduplication.

### Fixed
- Chip distribution (筹码分布): Tushare `cyq_chips` first (5000+ points), Akshare fallback. Serialize fetch (max_workers 1), delay 1.5–3s. Set `ENABLE_CHIP_DISTRIBUTION=false` if unstable.
- Picker API: Fix `PickerResponse() got multiple values for keyword argument 'picker_mode'` — remove redundant kwargs since `result_dict` already includes them.
- Stock code market detection: Add 001/003/004 prefixes for Shenzhen SME board (e.g. 003031). Tushare/Baostock/Yfinance now correctly map these to .SZ instead of falling back with warning.

### Added
- `PICKER_SPOT_TIMEOUT`: Timeout (seconds) for full-market spot data fetch (AkShare/efinance). Default 30. Increase when Eastmoney API is slow.
- `PICKER_ALLOW_LOSS`: When `true`, allow loss-making stocks (PE≤0) in picker pool. Default `false`.
- Picker backtest: `PickerBacktestService` runs quantitative screener historically, evaluates forward returns. API: `POST /api/v1/picker-backtest/run`, `GET /picker-backtest/performance`, `GET /picker-backtest/results`. Frontend: "选股回测" tab on Backtest page.
- Picker backtest persistence: Results saved to SQLite (`picker_backtest_history`). `GET /picker-backtest/history` (list), `GET /picker-backtest/history/{id}` (detail). Frontend loads last run from DB on tab switch (survives refresh), shows history list for quick switching.
- Stock screener `screen_as_of(trade_date)` for historical screening (Tushare only).
- `PUSH_REPORT_TYPE`: Separate report type for push notifications. When set (e.g. `brief`), push stays short while dashboard/file/Feishu doc remain detailed (`REPORT_TYPE`).
- `NOTIFY_ENABLED`: When `false`, disable all push notifications (for local runs). Default `true`.
- Stock picker bias filter: Layer 5 excludes candidates with MA5 bias > 8% (严进策略). Requires daily history from data provider.
- `--picker-only`: Run AI stock picker only (skip individual stock analysis and market review). Use `./test.sh picker` for quick verification.
- Stock picker 60-day change for Tushare: Compute 60日涨跌幅 via trade_cal + daily when using Tushare (AkShare spot already includes it).
- Stock picker constants: `VOLUME_RATIO_MIN`, `TREND_DECAY_THRESHOLD_PCT` for maintainability.
- `./test.sh picker-validation`: Offline validation of picker logic (60d decay, volume filter, prompt).

### Changed
- `daily_analysis.yml`: Split into 3 parallel jobs — `market-review` (45min), `stocks` (120min), `picker` (45min). Each job runs independently; schedule runs all 3, manual dispatch supports `full` / `market-only` / `stocks-only` / `picker-only`. Artifacts: `analysis-market-*`, `analysis-stocks-*`, `analysis-picker-*`.
- Backtest page: Improve layout and styling — gradient hero, segmented tabs, grid params for picker backtest.
- Picker backtest: Speed up — cache stock_basic (saves 1 Tushare call/day), batch benchmark fetch (N→1), parallelize forward returns (5 workers).
- Tushare: Pass token directly to `pro_api(token=...)` instead of `set_token()` to avoid writing `~/tk.csv`. Fixes "Operation not permitted" in sandbox/restricted environments (e.g. macOS, Docker).
- Stock picker: Use last A-share trading day (via exchange_calendars) when today has no Tushare data (e.g. weekends). Fixes empty quant pool on Saturday/Sunday.
- Stock picker: Spot data fetch timeout 10s → 30s (configurable via `PICKER_SPOT_TIMEOUT`).
- Workflow default: `REPORT_TYPE=simple` (detailed analysis/dashboard), `PUSH_REPORT_TYPE=brief` (short push).
- `docs/analysis-strategy-guide.md`: Added AI picker bias filter description, chase-risk exclusion (today > 9%), scope and limitations section.
- Stock picker: LLM picks 1-5 (was 3-8), explicit empty-position trigger (乖离率>5%占比>60%).
- Stock picker: 60-day gain >30% score decay to avoid end-of-trend buys.
- Stock picker: Volume ratio filter 0.8 → 1.0 to exclude cold stocks.
- Stock picker: PE filter 200 → 100 (PE_MAX constant).
- Stock picker: Limit-up streak filter — exclude 2+ limit-up days in last 5 days (连板/妖股).
- Stock picker: Board-specific limit-up threshold (main 10%, ChiNext/STAR 20%).
- Stock picker: Chip concentration in AI prompt (concentration_90, profit_ratio) when enabled.
- Stock picker: Industry dispersion constraint in prompt.
- `BIAS_THRESHOLD`: When not set, derive from `PICKER_MODE` (defensive 6%, balanced 8%, offensive 10%).
- Picker prompt: Align bias best-buy range with 买卖点规则 (2%/5%); replace "缩量回踩优先" with "量能配合的回踩" to match volume filter (量比>1).

### Removed
- Unused: `send_daily_report`, `get_notification_service` (notification.py); `analyze_stock` wrapper (stock_analyzer.py); `RealtimeQuote` alias (akshare); `EfinanceRealtimeQuote` (efinance); module-level test blocks in notification.py and stock_analyzer.py.
