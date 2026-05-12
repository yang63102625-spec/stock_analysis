# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

> For user-friendly release highlights, see the [GitHub Releases](https://github.com/jiasanpang/stock_analysis/releases) page.

## [Unreleased]

### Refactor: split the last two 800+ line modules (T4.4-followup)

Closes the rule §1 overflow tracked in the T4.4 wrap-up below — no
file in the repository now exceeds 800 lines.

- ``src/enhanced_market_analyzer.py`` (825 → 712): the five
  dataclasses + ``MarketSentiment`` enum that previously sat at the
  top of the file moved to ``src/_enhanced_market_types.py`` (140
  lines). ``EnhancedMarketAnalyzer`` re-imports them at module level
  so existing
  ``from src.enhanced_market_analyzer import EnhancedMarketReport``
  call sites keep working.
- ``src/services/backtest_service.py`` (815 → 635): the
  score-effectiveness helpers (``analyze_score_effectiveness``,
  ``_pearson_correlation``, ``_generate_score_conclusion``) moved
  into ``src/services/_backtest_score_mixin.py`` as
  ``_ScoreEffectivenessMixin``; ``BacktestService`` inherits from it
  so the public surface is unchanged.
- Concurrent fix: three lingering imports of the deleted
  ``src.services.picker.quantitative_filter`` shim
  (``picker/__init__.py``, ``picker/constants.py``,
  ``picker/service.py``, ``picker/realtime_filter.py``) updated to
  import ``StockScreener`` from ``src.services.picker.screener``
  directly. The shim was removed in commit ``32de82a`` ("drop all
  legacy backward-compatibility shims") but the call sites had not
  yet been migrated.

### Phase 4 wrap-up (T4.4)

After T4.1–T4.3 the suite stands at 662 tests passing (4 added in
T4.3, 11 added in T4.2, 13 migrated in T4.1). Two pre-existing
failures remain and are explicitly out of scope:

- ``tests/test_agent_pipeline.py::TestAgentConfig`` — depends on a
  removed ``Config._load_from_env`` helper.
- ``tests/test_agent_pipeline.py::TestPipelineRouting`` — depends
  on an undefined ``SearchService`` symbol.

**Known rule §1 overflows** (file-size limit 800 lines):

- ``src/enhanced_market_analyzer.py`` — 825 lines.
- ``src/services/backtest_service.py`` — 815 lines.

Both predate Phase 3 and were not touched by Phase 4 changes; they
will be split in a follow-up commit (same mixin / sub-module pattern
used in Phase 3 — see T3.1–T3.4 entries below). Tracking in the
plan as a deferred Phase-3 item rather than blocking the Phase-4
deliverables.

### Refactor: thread-safety + typed circuit-breaker state (T4.3)

Implements rule §6 ("Thread Safety") for the two pieces of shared
mutable state that are read/modified from worker threads.

- ``data_provider/realtime_types.py``:
  - The previous ``Dict[str, Dict[str, Any]]`` per-source state is
    replaced by a typed ``_SourceState`` dataclass
    (``state``, ``failures``, ``last_failure_time``, ``half_open_calls``).
  - ``CircuitBreaker`` now wraps every read-modify-write sequence in
    ``threading.Lock`` (``is_available`` / ``record_success`` /
    ``record_failure`` / ``get_status`` / ``reset`` / ``_get_state``).
    The breaker is consulted concurrently from realtime fetcher
    threads and bot dispatchers, so the previous lock-free
    implementation could lose ``failures += 1`` increments under
    contention.
- ``bot/dispatcher.py``:
  - ``RateLimiter`` (sliding-window) now holds a ``threading.Lock``
    around the prune-then-check-then-append window operation. Bot
    platforms (DingTalk / Feishu / Discord) spawn a fresh worker
    thread per incoming message, so the read-modify-write on
    ``self._requests[user_id]`` was racy and could let users exceed
    the configured cap.
  - Pruning logic factored into ``_prune_locked`` to share between
    ``is_allowed`` and ``get_remaining``.
- ``tests/test_thread_safety.py`` (new, 4 cases): hammers the
  breaker from 16 concurrent workers (no corruption / state stays
  consistent) and asserts ``RateLimiter`` enforces the cap exactly
  under contention (200 attempts / cap=50 → 50 granted).

### Refactor: shared DataFrame validators wired into all OHLCV fetchers (T4.2)

Implements rule §7 from ``code-quality.mdc`` ("Data Validation Rules").

- ``data_provider/validators.py`` (new): canonical validator module.
  - ``validate_ohlcv_dataframe(df, *, context, ...)`` — non-empty
    check, required-column check, optional numeric coercion, plus
    financial-integrity checks (negative price/volume rejected;
    ``close == 0`` flagged as warning during a trading session;
    ``|pct_chg| > 20%`` flagged as warning).
  - ``validate_dataframe(df, *, required_columns, dtype_map)`` —
    generic non-OHLCV variant for fundamentals / moneyflow frames.
  - ``validate_required_columns`` and ``coerce_numeric_columns``
    exposed as low-level helpers.
- All six historical-data fetchers now call
  ``validate_ohlcv_dataframe`` before truncating to ``STANDARD_COLUMNS``:
  ``data_provider/yfinance_fetcher.py``,
  ``data_provider/pytdx_fetcher.py``,
  ``data_provider/baostock_fetcher.py``,
  ``data_provider/efinance/historical.py``,
  ``data_provider/akshare/historical.py``,
  ``data_provider/tushare/historical.py``.
- ``tests/test_dataframe_validators.py`` (new, 11 cases): covers empty
  / missing-column / negative-value / zero-close / extreme-pct-chg
  paths plus the dtype-coercion helper.

### Refactor: unify all API responses into the ``APIResponse`` envelope (T4.1)

Implements rule §3 ("API Response Format") from ``code-quality.mdc``: every
``/api/*`` endpoint now returns the canonical
``{code, message, data, timestamp}`` envelope, both on success and on error.

**Backend**

- ``api/v1/schemas/envelope.py`` (new): defines ``APIResponse[T]`` (Pydantic
  generic), ``ApiErrorCode`` (``IntEnum`` taxonomy: 0 success, 1xxx client,
  2xxx upstream, 9xxx server) and ``success_response`` / ``error_response``
  helpers. Timestamp uses Beijing time (ISO-8601 with offset).
- ``api/v1/envelope_route.py`` (new): ``EnvelopeRoute`` (``APIRoute``
  subclass) wraps every handler return value into ``APIResponse(data=…)``
  before FastAPI runs ``response_model`` validation. Handlers keep the
  ergonomic ``return X`` style; pre-built ``Response`` /
  ``StreamingResponse`` / ``EventSourceResponse`` instances pass through.
- ``api/middlewares/error_handler.py``: rewritten to emit the envelope for
  every exception path. Maps project exceptions
  (``RateLimitError`` / ``NetworkError`` / ``DataSourceUnavailableError`` /
  ``ValidationError`` / ``DataFetchError``) and ``HTTPException`` to a
  fixed ``ApiErrorCode``. Legacy ``detail={"error": …, "message": …}``
  shape is no longer special-cased — endpoints must use plain-string
  ``detail`` (or raise project exceptions) and let the handler envelope.
- ``api/middlewares/auth.py``: 401 unauthorized now returns the envelope
  via ``error_response(ApiErrorCode.UNAUTHORIZED, …)``.
- ``api/v1/endpoints/*.py`` (11 files): every ``router = APIRouter()``
  swapped for ``APIRouter(route_class=EnvelopeRoute)``; all 28
  ``response_model=X`` annotations updated to
  ``response_model=APIResponse[X]`` (OpenAPI now reflects the wire
  contract).
- ``api/v1/endpoints/auth.py``: 11 ``JSONResponse(content={"error": …})``
  calls migrated to ``error_response(ApiErrorCode.…, msg)``;
  ``content={"ok": True}`` → ``success_response()``.
- ``api/v1/endpoints/analysis.py``: 202 Accepted and 409 duplicate-task
  paths now wrap their bodies via ``success_response`` /
  ``error_response`` so the envelope is consistent across status codes.
  The 409 ``data`` field carries the structured
  ``{stock_code, existing_task_id}`` for the front-end.
- 39 ``raise HTTPException(detail={"error": …, "message": …})`` call
  sites across ``stocks.py`` / ``analysis.py`` / ``picker_backtest.py`` /
  ``system_config.py`` / ``backtest.py`` / ``history.py`` reduced to
  plain-string ``detail`` so the global handler can envelope them
  uniformly.
- ``api/app.py``: ``/api/health`` moved onto an ``EnvelopeRoute`` router
  so it is enveloped like the v1 endpoints; SPA fallback for paths
  starting with ``/api/`` now raises ``HTTPException(404)`` instead of
  silently returning ``None`` (which previously surfaced as 200 ``null``).

**Frontend (``apps/dsa-web``)**

- ``src/api/index.ts``: response interceptor auto-unwraps the envelope —
  for any 2xx response with ``code === 0`` it replaces ``response.data``
  with ``response.data.data`` so existing callers keep working unchanged.
  Non-2xx (e.g. 409 with ``validateStatus``) keeps the raw envelope so
  callers can read structured error fields.
- ``src/api/analysis.ts``: ``analyzeAsync`` 409 branch reads the new
  envelope shape (``envelope.message`` + ``envelope.data.stock_code`` /
  ``envelope.data.existing_task_id``) when constructing
  ``DuplicateTaskError``.

**Tests**

- ``tests/test_auth_api.py``: assertions migrated from
  ``response.json()["ok"]`` / ``response.json()["error"]`` to the
  envelope (``code === 0`` for success, ``code === 1001`` for
  ``VALIDATION_ERROR``).
- ``tests/test_system_config_api.py``: GET / PUT assertions migrated to
  read ``response.json()["data"]``; the 409 conflict assertion now
  checks ``code === 1099`` and ``message`` containing
  ``"config_version"``.
- Suite: 647 passed (the two remaining failures —
  ``Config._load_from_env`` and ``SearchService`` — are pre-existing and
  unrelated to this change).

### Refactor: trim the four remaining 800+ line modules (T3.4)

- ``main.py`` (842 → 671): the 172-line ``parse_arguments`` function
  moved to ``src/cli/args.py`` (re-exported via ``src.cli``).
- ``src/notification_service/aggregator.py`` (919 → 523): the long
  ``generate_dashboard_report`` and ``generate_wechat_dashboard``
  methods extracted into ``_dashboard_mixin.py``;
  ``ReportAggregatorMixin`` now inherits from ``_DashboardMixin``.
- ``src/stock_analyzer.py`` (1125 → 556): enums + ``TrendAnalysisResult``
  moved to ``src/_stock_analyzer_types.py``; the 343-line
  ``_generate_signal`` plus ``format_analysis`` moved to
  ``src/_stock_analyzer_signals.py``. Public surface unchanged
  (``__all__`` re-exports the seven canonical symbols).
- ``data_provider/efinance_fetcher.py`` (1169 lines, gone) replaced by
  the ``data_provider/efinance/`` sub-package, mirroring the existing
  ``akshare`` / ``tushare`` layout: ``utils.py``, ``base.py``
  (``_EfinanceCore``), ``historical.py``, ``realtime.py``,
  ``market.py``, ``fetcher.py``. All callers updated to
  ``from data_provider.efinance import EfinanceFetcher`` —
  ``tests/test_backward_compat_imports.py`` likewise.

### Refactor: split ``src/core/pipeline.py`` (1616 lines) into ``pipeline/`` package

- ``src/core/pipeline.py`` is gone; the class composition lives in five
  files under ``src/core/pipeline/``, each ≤ 785 lines (rule §1):
  - ``__init__.py`` — class signature + ``__init__`` +
    ``fetch_and_save_stock_data`` + re-exports the patch targets used
    by tests (``get_config`` / ``get_db`` / ``DataFetcherManager`` …).
  - ``_analysis_mixin.py`` — per-stock analysis (``analyze_stock``,
    context enhancement, agent invocation, result conversion).
  - ``_market_env_mixin.py`` — market-environment cache + context
    augmentation helpers.
  - ``_run_mixin.py`` — top-level ``run`` and ``process_single_stock``.
  - ``_notify_mixin.py`` — aggregate-report and notification dispatch.
- ``tests/test_pipeline_realtime_indicators.py`` patch paths updated
  from ``src.core.pipeline.{is_market_open,get_market_for_stock}`` to
  ``src.core.pipeline._market_env_mixin.{...}`` to match the new
  import location.

### Refactor: split ``src/core/config_registry.py`` (1581 lines) into ``config_registry/`` package

- The monolithic field-metadata file is gone. The contents are split
  into ``categories.py``, ``fields_a.py``, ``fields_b.py``,
  ``_inference.py`` and ``__init__.py`` — each ≤ 695 lines (rule §1).
- The 94 field definitions are split alphabetically into ``fields_a``
  (base / ai_model / data_source / first half of notification) and
  ``fields_b`` (rest of notification / system / agent / backtest), then
  merged in ``__init__.py`` via ``{**_FIELD_DEFS_A, **_FIELD_DEFS_B}``.
- Public API (``get_category_definitions`` / ``get_field_definition`` /
  ``get_registered_field_keys`` / ``build_schema_response`` /
  ``SCHEMA_VERSION``) is unchanged; the only call site
  (``src/services/system_config_service.py``) requires no edits.

### Refactor: split ``data_provider/base.py`` (1445 lines) into ``base/`` sub-package

- ``data_provider/base.py`` is gone; its contents live in seven focused
  files under ``data_provider/base/``, each ≤ 327 lines (rule §1):
  - ``__init__.py`` — public surface re-exports.
  - ``codes.py`` — stock-code helpers and exception summarisation.
  - ``fetcher.py`` — ``BaseFetcher`` ABC.
  - ``_realtime_mixin.py`` / ``_names_mixin.py`` / ``_market_mixin.py``
    — three internal mixins composed by ``DataFetcherManager``.
  - ``manager.py`` — ``DataFetcherManager`` (multi-mixin) singleton.
- All existing call sites (``api/`` / ``bot/`` / ``main.py`` / ``src/``
  / ``tests/``) keep working unchanged — public surface re-exported
  from ``data_provider.base``.
- Three latent stale imports surfaced and fixed during the split:
  ``from .akshare_fetcher`` / ``from .tushare_fetcher`` were left over
  from earlier shim removal; rewritten to the canonical
  ``from ..akshare`` / ``from ..tushare`` package paths.

### Refactor: split ``src/analyzer.py`` (1561 lines) into ``src/analyzer/`` package

- ``src/analyzer.py`` is gone; its contents live in eight focused modules
  under ``src/analyzer/`` and every file is now ≤ 513 lines (rule §1):
  - ``__init__.py`` — public surface re-exports.
  - ``integrity.py`` — content-integrity helpers + chip_structure fallback.
  - ``stock_name.py`` — multi-source stock-name resolver.
  - ``result.py`` — ``AnalysisResult`` dataclass.
  - ``_llm_client.py`` — ``_LLMClientMixin`` (LiteLLM Router init,
    ``generate_text``).
  - ``_prompt_builder.py`` — ``_PromptBuilderMixin`` (prompt assembly,
    market-snapshot helpers, formatters).
  - ``_response_parser.py`` — ``_ResponseParserMixin`` (JSON / text
    parsing into ``AnalysisResult``).
  - ``gemini.py`` — ``GeminiAnalyzer`` (composes the three mixins) +
    system-prompt constants + ``analyze`` / ``batch_analyze`` /
    integrity helper methods + ``get_analyzer`` factory.
- Public surface is unchanged: every existing
  ``from src.analyzer import …`` call site keeps working without
  modification.
- ``__main__`` diagnostic block (~33 lines) dropped — production code
  paths are exercised by ``tests/`` and ``scripts/diagnose_env.py``.

### Refactor: unified TTLCache for all data-provider module caches

- Replaced six raw module-level cache dictionaries with the unified
  ``TTLCache`` (`data_provider.caching_manager`):
  - ``data_provider/akshare/utils.py``: ``_realtime_cache`` /
    ``_etf_realtime_cache``.
  - ``data_provider/efinance_fetcher.py``: ``_realtime_cache`` /
    ``_etf_realtime_cache``.
  - ``data_provider/tushare/realtime.py``: ``_realtime_list_cache`` /
    ``_rt_k_cache`` / ``_daily_basic_cache`` / ``_daily_vol_avg_cache``
    (also drops the parallel ``_*_cache_time`` / ``_*_cache_date``
    sentinel variables).
- All caches now have explicit TTL, thread-safe get/set, and built-in
  hit/miss observability — satisfies ``code-quality.mdc`` rule §5
  ("Cache MUST be managed through a unified interface").
- ``src/services/picker/screener/data_fetch.py`` switched from poking
  cache-internal timestamps to the canonical
  ``TTLCache.clear()`` to force a refresh.
- ``tests/test_backward_compat_imports.py`` updated to track the renamed
  ``_rt_k_cache`` symbol.

### Refactor: drop legacy backward-compatibility shims

- Removed all 7 shim files left behind by phases 1-2 refactors:
  ``src/notification.py``, ``src/wechat_formatter.py``, ``src/formatters.py``,
  ``src/services/stock_picker_service.py``,
  ``src/services/picker/quantitative_filter.py``,
  ``data_provider/tushare_fetcher.py``,
  ``data_provider/akshare_fetcher.py``.
- All call sites (16 production modules + 4 test files + 1 GitHub workflow
  + ``test.sh``) updated to import directly from the canonical paths
  (``src.notification_service`` / ``src.notification_service.wechat_formatter``
  / ``src.notification_service.formatters`` / ``src.services.picker`` /
  ``src.services.picker.screener`` / ``data_provider.tushare`` /
  ``data_provider.akshare`` and their ``utils`` / ``realtime`` submodules).
- ``data_provider/__init__.py`` now imports ``AkshareFetcher`` /
  ``TushareFetcher`` from their respective canonical sub-packages.
- ``tests/test_backward_compat_imports.py`` rewritten to assert the
  canonical public surface only (legacy shim entries removed).
- Exception classes (``DataFetchError`` / ``RateLimitError`` /
  ``DataSourceUnavailableError``) consolidated: they now live only in
  ``src.exceptions``. ``data_provider/base.py`` imports them from there
  instead of defining its own copies, and every fetcher / test was
  updated to import from ``src.exceptions`` directly.
- New rule added in ``.cursor/rules/code-quality.mdc`` (section 1b) and
  ``AGENTS.md`` § 1: **single source of truth — no shims, no legacy
  paths.** Renames/moves must update all callers and delete the old
  file in the same change.

### Refactor: code quality phase 2.4 (split search service)

- ``src/search_service.py`` (2019 lines) replaced by the
  ``src.search_service`` sub-package. Each search provider gets its own file
  (``tavily.py`` / ``serpapi.py`` / ``bocha.py`` / ``minimax.py`` /
  ``brave.py`` / ``searxng.py``) plus shared modules:
  ``http_utils.py`` (``_post_with_retry`` / ``_get_with_retry`` /
  ``fetch_url_content``), ``models.py`` (``SearchResult`` / ``SearchResponse``
  dataclasses), ``base_provider.py`` (``BaseSearchProvider`` ABC),
  ``service.py`` (``SearchService`` orchestrator + ``get_search_service`` /
  ``reset_search_service`` singleton helpers).
- Largest split file is ``service.py`` at 732 lines; every provider stays
  well under the 800-line ceiling.
- Package ``__init__.py`` re-exports every public symbol so existing
  imports (``from src.search_service import SearchService`` / provider
  classes / dataclasses / module-level helpers) keep working.
- Tests that mocked ``src.search_service.requests.get`` /
  ``src.search_service.datetime`` were updated to point at the canonical
  module locations (``http_utils.requests`` / ``service.datetime``).

### Refactor: code quality phase 2.3 (split storage layer)

- ``src/storage.py`` (2175 lines) replaced by the ``src.storage`` sub-package:
  ``models.py`` (all 9 ORM models + ``Base``), ``manager_base.py``
  (singleton/engine/session lifecycle + schema migrations),
  ``daily_data.py`` (StockDaily queries + ``save_daily_data``),
  ``news.py`` (NewsIntel CRUD), ``analysis.py`` (AnalysisHistory CRUD +
  ``get_analysis_context`` + helpers), ``picker.py`` (picker history +
  picker backtest history), ``conversation.py`` (chat session/messages),
  ``llm_usage.py`` (LLMUsage audit log), ``manager.py`` (composes the
  mixins; module-level ``get_db`` / ``persist_llm_usage``).
- Largest split file is ``analysis.py`` at 613 lines; the package
  ``__init__.py`` re-exports every public symbol so existing imports
  (``from src.storage import DatabaseManager`` / ``get_db`` /
  ``persist_llm_usage`` / any ORM model) continue to work without changes.
- ``DatabaseManager.__init__`` keeps registering the atexit cleanup hook
  via ``type(self)._cleanup_engine`` so the inheritance chain stays
  decoupled from a hard-coded ``DatabaseManager`` reference.

### Refactor: code quality phase 2.2 (split StockScreener)

- ``src/services/picker/quantitative_filter.py`` (1671 lines) split into the
  ``src.services.picker.screener`` sub-package: ``base.py`` (shared state +
  small helpers + risk-filter delegations), ``data_fetch.py`` (spot/Tushare
  bulk + realtime overlay + normalisation), ``filters_scoring.py`` (basic
  filter / hard veto / momentum / volume / scoring), ``pipeline.py``
  (``screen()`` and ``screen_as_of()``), ``eod_buyback.py`` (the dedicated
  realtime EOD path), ``screener.py`` (composes the mixins).
- Each split file is ≤556 lines (largest: ``data_fetch.py``).

### Refactor: code quality phase 2.1 (split Tushare/Akshare fetchers)

- ``data_provider/tushare_fetcher.py`` (2056 lines) split into the
  ``data_provider.tushare`` sub-package: ``base.py`` (init/rate-limit/code conv),
  ``historical.py`` (daily/ETF/chip), ``realtime.py`` (full-market snapshots,
  ``rt_k`` and ``daily_basic`` caches), ``market.py`` (indices/market_stats/sector),
  ``utils.py`` (helpers/constants), ``fetcher.py`` (composes the mixins).
  Each file is now ≤800 lines.
- ``data_provider/akshare_fetcher.py`` (1869 lines) split into the
  ``data_provider.akshare`` sub-package along the same axes
  (``base``/``historical``/``realtime``/``market``/``utils``/``fetcher``).
- ``tests/test_akshare_realtime_logging.py``: ``monkeypatch.setattr`` targets
  retargeted to the new ``data_provider.akshare.realtime`` module so the patch
  hits the actual call site.

### Refactor: code quality phase 1 (anti-crawl / exception / cache convergence)

- `data_provider/rate_limit_mixin.py`: ``_last_request_time`` is now a per-instance
  attribute guarded by an instance-level ``threading.Lock`` (no more class-shared race).
- `tushare_fetcher`, `baostock_fetcher`, `yfinance_fetcher`, `pytdx_fetcher` now inherit
  ``RateLimitMixin`` so all six A-share fetchers share the same anti-crawl helpers.
- `src/exceptions.py`: unified taxonomy (``DataFetchError`` base +
  ``RateLimitError`` / ``NetworkError`` / ``DataSourceUnavailableError`` /
  ``ValidationError`` / ``UnknownError``) is now the single source of truth.
  ``data_provider.base`` and every fetcher imports the classes from here.
- `BaseFetcher._classify_exception(exc)` returns the taxonomy class (companion to the
  existing string-tuple ``_classify_error``).
- `data_provider/caching_manager.py`: added ``TTLCache`` (per-entry TTL, hit/miss
  stats, ``threading.RLock``) and ``trading_session_ttl`` helper.
- `data_provider/fundamentals_fetcher.py`: migrated the bespoke
  ``FundamentalsCache`` dataclass + four manual double-check-locked ``_ensure_*``
  helpers onto ``TTLCache`` (drops ~80 lines of boilerplate, no behaviour change).
- Cleanup: moved root-level diagnostic scripts ``test_env.py``,
  ``test_enhanced_review.py``, ``test_realtime_filter_demo.py``,
  ``test_verification.py`` and ``scripts/test_picker_backtest.py`` to
  ``scripts/diagnose_env.py`` / ``check_enhanced_review.py`` /
  ``demo_realtime_filter.py`` / ``verify_search_service.py`` /
  ``run_picker_backtest.py``. Updated docs and ``.gitignore``.
- Entry-point inventory: ``main.py`` (CLI), ``server.py`` (FastAPI),
  ``webui.py`` (env-var launcher) and ``analyzer_service.py`` (programmatic
  service facade documented in ``SKILL.md``) all kept — each has a distinct,
  user-visible role.

### Cleanup: remove backtest engine v1 entirely

- Dropped the `backtest_engine_version` config knob, the `BACKTEST_ENGINE_VERSION` env var,
  and the corresponding entry in `src/core/config_registry.py` / WebUI i18n.
- Dropped the `engine_version` column from `backtest_results` and `backtest_summaries`
  (SQLite `ALTER TABLE ... DROP COLUMN`), removed `EvaluationConfig.engine_version` and the
  `BacktestEngine.ENGINE_VERSION` constant, and rebuilt the unique indexes
  (`backtest_results` → `(analysis_history_id, eval_window_days, strategy_id)`,
  `backtest_summaries` → `(scope, code, eval_window_days)`).
- Also dropped the legacy `advice_breakdown_json` column / API field / TS type — the v2
  `signal_breakdown / score_bucket_breakdown / exit_reason_breakdown / regime_breakdown /
  strategy_breakdown` panels fully replace it.
- The one-shot wipe migration introduced earlier still runs once on first init so any
  stale rows from the old schema are erased before the column drop.

### Individual Stock Backtest: per-strategy multi-run

- API: `POST /api/v1/backtest/run` now accepts an optional `strategies: string[]` payload
  (subset of `buy_pullback / breakout / bottom_reversal / eod_buyback`). When supplied,
  each analysis record is evaluated once per strategy and persisted as a separate
  `BacktestResult` row, so users can compare per-strategy win rate / R/R / exit reasons
  side by side in the existing breakdown panel.
- DB: extended the `backtest_results` unique key to
  `(analysis_history_id, eval_window_days, engine_version, strategy_id)`. SQLite migration
  drops the old index and creates the new one in place.
- Service: shared data fetch (start price + forward bars) is reused across strategies,
  only the trade-levels evaluation runs per strategy. `force=True` rerun replaces only the
  rows whose `strategy_id` matches the new run, so other strategies for the same analysis
  are kept.
- WebUI: the individual-stock backtest "Controls" card grew a `回测策略` chip row mirroring
  the picker UI; defaults to `买回踩` and supports multi-select.

### BREAKING: Individual Stock Backtest Engine v2 (signal-driven, trade-levels-aware)
- **Engine rewritten** (`src/core/backtest_engine.py`): no longer parses LLM `operation_advice` text. Now driven by:
  - System-computed `buy_signal` (`STRONG_BUY` / `BUY` → long; `HOLD` / `AVOID` / `STRONG_AVOID` → cash). Eliminates Chinese-keyword fragility.
  - Unified `simulate_forward_trade` (same engine as picker backtest): staged exits, MA10 trailing, ATR×2.5 retracement, slippage, limit-up entry filter.
- **`engine_version` bumped to `v2`**. Default in `Config` and `BACKTEST_ENGINE_VERSION` env var both updated.
- **DB schema extended** (`backtest_results` adds 16 columns, `backtest_summaries` adds 5 JSON columns): `signal_score_at_eval` / `buy_signal_at_eval` / `market_environment_at_eval` / `strategy_id` / `risk_reward_at_eval` / `position_pct_at_eval` / 7 dim score snapshots / `exit_reason` / `hold_days`. Summaries now carry `signal_breakdown_json` / `score_bucket_breakdown_json` / `exit_reason_breakdown_json` / `regime_breakdown_json` / `strategy_breakdown_json`.
- **One-shot data wipe**: on first DB init under v3.x+, all legacy `backtest_results` / `backtest_summaries` rows are DELETEd (note: the `engine_version` column referenced here was later dropped entirely — see top of changelog). Re-run `/api/v1/backtest/run` to regenerate. Pre-v3.0 analyses (which lack `signal_score`) yield `eval_status='missing_signal'` and are skipped.
- **API + WebUI**:
  - `BacktestResultItem` exposes the 16 new fields; `PerformanceMetrics` exposes 5 breakdown dicts.
  - `BacktestPage.tsx` individual-backtest table replaces 「建议 / 止损 / 止盈」 columns with 「信号 / 量化分 / 策略 / 持仓 / 退出原因」.
  - New `BreakdownGrid` panel under `PerformancePanel` shows win-rate by signal / score-bucket / exit_reason / regime / strategy.
- **Tests**: `tests/test_backtest_engine.py` rewritten for v2 (15 cases covering signal mapping, missing_signal handling, simulate_forward_trade integration, breakdown aggregation). `tests/test_backtest_summary.py` updated to v2 row shape.

### Fixed (Picker Backtest WebUI: expose exit_reason / hold_days / strategy)
- **`PickResult` extended** with `exit_reason` (e.g., `stop_loss` / `trailing_ma10` / `stage_break_+12pct` / `hardcap_+20pct` / `window_end`), `hold_days`, and `strategy_id`. Previously `simulate_forward_trade` returned these but the picker backtest pipeline dropped them on the floor.
- **`_get_forward_return` signature changed** from `Tuple[exit_price, return_pct]` to `Dict[str, Any]` so the parallel runner can propagate the diagnostic fields.
- **API + TS schema + WebUI table** updated: results table now shows 持仓 / 退出原因 / 策略 columns. Users can finally diagnose *why* a backtest pick lost money (止损 vs 移动止盈 vs 窗口到期 vs 硬顶平仓).

### Fixed (Analysis WebUI: expose system signals & trade-level extras)
- **DB schema extended** (`AnalysisHistory`): added `signal_score` / `buy_signal` / `pe_ratio` / `market_environment` / `position_pct` / `risk_reward` / `take_profit_2_rule` columns. Auto-migration via `ALTER TABLE` (existing rows get NULL; new analyses populate full set).
- **save_analysis_history**: extracts the new fields from `context_snapshot.enhanced_context.{trend_analysis, trade_levels}` (computed by pipeline / trade_levels engine) and persists them.
- **API schemas** (`ReportSummary` / `ReportStrategy`): exposed `signal_score`, `buy_signal`, `pe_ratio`, `market_environment`, full per-dimension breakdown (`trend_score` / `bias_score` / `volume_score` / `support_score` / `macd_score` / `rsi_score` / `capital_flow_score`), and trade-level extras (`position_pct` / `risk_reward` / `take_profit_2_rule`). These were previously computed but silently dropped at the Pydantic boundary.
- **WebUI**: new `ReportScores` panel shows total quant score (0-100), `buy_signal` badge, market regime, PE, and a 7-dim score-bar breakdown. `ReportStrategy` now also renders 建议仓位 / 盈亏比 R/R / 后续止盈规则.
- **Stale comments fixed** in `storage.py` (`support_score` 0-12 → 0-6, `macd_score` 0-10 → 0-13, `capital_flow_score` 0-10 → 0-13 weighted) to match the post-rebalance scoring.

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

### Changed (Picker Quality Tightening — Post-run Review)
- **`BOTTOM_REVERSAL.pe_max` 100 → 60**: reversal strategy is mean-reversion bet on oversold names; PE>60 with -15-20% drawdown rarely qualifies as a true "low base" — historical win rate <30% in this band. Tightening filters out high-PE "fake reversals" (e.g. mid-cap "白马" rebounds).
- **Industry concentration cap (E2)**: post-merge filter keeping at most N (default 2, env `PICKER_INDUSTRY_TOP_N`) highest-scoring candidates per SW L1 industry. Prevents sector-beta blow-ups where one industry can dominate the picker pool. New `ScreenedStock.industry` field (best-effort from Tushare `stock_basic`); cap silently skipped when industry data unavailable.

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
- Demo script: `scripts/demo_realtime_filter.py` shows filtering logic in action

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
