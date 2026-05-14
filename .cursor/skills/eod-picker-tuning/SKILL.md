---
name: eod-picker-tuning
description: Iteratively tune the eod_buyback (尾盘买入) picker strategy to raise its backtest win rate. Runs `PickerBacktestService` over a recent window with `top_n=2`, parses summary + per-pick failures, proposes one parameter change at a time backed by professional A-share trading rationale, re-runs, and stops when win rate plateaus. Use when the user asks to "提高选股回测胜率", "优化尾盘策略", "tune eod_buyback", "跑尾盘选股回测", or wants iterative strategy improvement with empirical evidence. Always invokes the user before adding a new Tushare API or external data source.
disable-model-invocation: true
---

# EoD Picker Tuning Loop

Iterative optimization of the `eod_buyback` picker strategy. Runs the
backtest, diagnoses what kills the win rate, proposes one targeted change
backed by professional A-share trading reasoning, re-runs, compares.

## Hard Rules

- **Never** silently delete `picker_backtest_history` rows — they are the
  experiment ledger. If a stale run is misleading, rename / annotate it,
  don't drop it.
- **Never** push a parameter change live to `.env` or `config_registry`
  without the user's explicit "ok" — proposals only update the in-memory
  request payload of the next backtest run.
- **Never** add a new Tushare endpoint, AkShare API, or other data source
  without first asking the user which one is acceptable. The user has
  Tushare 8000 积分; that doesn't mean every endpoint is welcome.
- **Never** claim a win-rate improvement from a sample with `total_picks <
  20`. Below that, treat any delta as noise.
- **Never** use `--no-notify` flags here — this skill never touches
  `main.py`. Backtest runs go through `PickerBacktestService` directly.

## What "Win Rate" Means Here

`PickerBacktestSummary.win_rate_pct = win_count / (win_count + loss_count) * 100`

A pick is `win` iff the trade-levels engine's `simulate_forward_trade`
exits with positive `return_pct`. `insufficient` (no forward bars) is
excluded from both numerator and denominator. Treat win rate alongside:

- `avg_return_pct` — high WR with negative avg return = small wins, big
  losses (asymmetric tail)
- `profit_factor` — `sum_wins / |sum_losses|`. < 1 means losing system
  even at WR > 50%
- `max_drawdown_pct` — equity peak-to-trough on chronologically
  compounded picks
- `alpha_vs_benchmark_pct` — vs CSI 300 over the same window

Any "improvement" needs WR↑ AND profit_factor non-decreasing.

## Execution Loop

Track progress; tick as you go. One iteration = run + diagnose + propose
+ confirm + re-run.

```
Iteration N:
- [ ] Run baseline (or previous-best) backtest
- [ ] Parse summary + per-pick outcomes
- [ ] Diagnose top failure mode
- [ ] Propose one change (one variable!) with trader rationale
- [ ] Get user confirmation (use AskQuestion)
- [ ] Re-run with the change
- [ ] Compare WR / PF / drawdown vs previous best
- [ ] Decide: keep, revert, or iterate again
```

Stop conditions (any one):
1. Win rate hasn't improved by ≥ 2pp across two consecutive iterations
2. profit_factor falls below previous best
3. User says stop
4. You've changed the same parameter family twice in a row without gain
   — that family is a dead end; pivot or stop

## Step 0 — Preconditions

```bash
cd /Users/wei/Projects/tw/stock_analysis
ls .env .venv/bin/python > /dev/null && echo "env ok"
.venv/bin/python -c "from src.services.picker_backtest_service import PickerBacktestService; print('import ok')"
```

If import fails, stop and report — fixing infra is out of scope.

## Step 1 — Baseline Run

Use a **recent 3-month window ending on the most recent trading day** to
keep the regime relevant. Don't go further back unless the user asks.

```bash
.venv/bin/python <<'EOF'
from datetime import date, timedelta
from src.services.picker_backtest_service import PickerBacktestService

today = date.today()
end = today.strftime("%Y%m%d")
start = (today - timedelta(days=90)).strftime("%Y%m%d")

svc = PickerBacktestService()
res = svc.run(
    start_date=start,
    end_date=end,
    hold_days=10,
    top_n=2,
    picker_strategies=["eod_buyback"],
)
import json
s = res.get("summary") or {}
print("=== Summary ===")
for k in ("total_picks","win_count","loss_count","insufficient_count",
         "win_rate_pct","avg_return_pct","profit_factor",
         "max_drawdown_pct","alpha_vs_benchmark_pct"):
    print(f"  {k}: {s.get(k)}")
print(f"  trade_dates_count: {res.get('trade_dates_count')}")

# Sample 5 worst losers + 5 biggest insufficient streaks for context
results = res.get("results") or []
losers = [r for r in results if r.get("outcome")=="loss"]
losers.sort(key=lambda r: r.get("return_pct") or 0)
print(f"\n=== Worst 5 losers ===")
for r in losers[:5]:
    print(f"  {r['trade_date']} {r['code']}({r['name']}) "
          f"entry={r['entry_price']} exit={r.get('exit_price')} "
          f"ret={r.get('return_pct')}% reason={r.get('exit_reason')} hold={r.get('hold_days')}")
EOF
```

Persist baseline to memory: `baseline = {win_rate, pf, dd, alpha, n}`.

If `total_picks < 20`, **expand the window to 180 days** before
diagnosing. Below 20 picks, the noise floor swamps any signal.

## Step 2 — Diagnose Top Failure Mode

For losers, bucket by `exit_reason`:
- `stop_loss` heavy → entries are wrong (filter is too lax on quality)
- `window_end` heavy with negative ret → no thrust, picks are dead money
  → momentum/volume filter too lenient
- `trailing_ma10` with small negative → near-misses, often a regime
  mismatch issue (use during weak market)

For insufficient: usually means `hold_days` extends past the test window
edge — not a strategy issue.

Then bucket losers by **calendar regime** (you already saved
`market_environment_at_eval` if available):
- High `loss_count` concentrated in `bear` / `strong_bear` → add
  market-environment guard (already supported via
  `picker_market_guard=True`, check if disabled)
- Even spread → strategy itself is the issue, not regime

## Step 3 — Propose One Change (Trader Rationale Required)

Pick **one** lever from the table below. Write the rationale in the
proposal; don't change blindly.

| Lever | Where | A-share trader logic |
|---|---|---|
| Tighten `change_pct` upper bound from 6% → 5% | `src/services/picker/screener/eod_buyback.py:146` | Picks above +5% on close are often blow-off tops; next-day gap-down is common |
| Raise turnover floor from 5% → 7% | line 158 | <7% turnover on a +3-6% move = no real participation, fund flow is weak |
| Raise market-cap floor 60亿 → 80亿 | line 183 | Sub-80亿 易被游资拉抬制造假信号，机构难进难出 |
| Lower market-cap ceiling 300亿 → 200亿 | line 183 | 300亿+ 大票尾盘异动多为指数资金推动，无个股 alpha |
| Add 5日均线斜率正过滤 | new filter | 截图式买入易踩反弹中继；需 ma5 上行 |
| Add前一日非涨停过滤 | new filter | 涨停次日的 +3-6% 多为出货，胜率显著低 |
| 切换 `hold_days` 10 → 5 | run param | 尾盘买入是短线策略，10 天太长，趋势衰减后命中率下降 |
| Add 北向资金净流入过滤（需 `moneyflow_hsgt`） | new data source | 需先问用户是否同意接 Tushare moneyflow_hsgt（积分 ok 但属于新依赖） |
| Add 主力净流入过滤（需 `moneyflow`） | new data source | 同上 |
| Add 龙虎榜机构净买入加分（需 `top_list`） | new data source | 同上 |

**Never combine two changes in one iteration** — you'll lose attribution.

## Step 4 — Confirm and Re-Run

Use `AskQuestion` with the proposal:

- title: "下一轮回测调整"
- prompt: "本轮提议：<change>。理由：<rationale>。预期：WR <baseline> → <target>。"
- options:
  - `apply` — 同意按此参数重跑
  - `different` — 想换另一个 lever
  - `add_data` — 同意加新数据源（仅当提议涉及新 API）
  - `stop` — 停止迭代

If `apply`, monkey-patch the parameter in the run script (do NOT edit
`.py` files unless the user asks). Example for `change_pct` upper:

```python
# In the run script:
import src.services.picker.screener.eod_buyback as eod
# Find the constant or patch the filter inline by reading + replacing
# in the loaded module before calling svc.run(...).
```

For threshold changes that live as magic numbers in eod_buyback.py
(e.g. `3.0`, `6.0`, `5.0`, `12.0`, `60.0`, `300.0`), the cleanest
non-destructive way is:

```python
import src.services.picker.screener.eod_buyback as mod
src_orig = mod._EodBuybackMixin._screen_eod_buyback_realtime.__wrapped__ \
    if hasattr(mod._EodBuybackMixin._screen_eod_buyback_realtime, '__wrapped__') \
    else None
# Better: copy eod_buyback.py to /tmp, sed-replace the constant, exec into a
# fresh module, monkey-patch screener._eod_mixin.
```

If that gets ugly, switch to **temporary edit** of
`src/services/picker/screener/eod_buyback.py`, run, then `git checkout`
the file. Note this in the report so the user knows the file was
touched.

If `add_data` is approved for a new Tushare endpoint, follow the
`data-source-priority.mdc` rules: extend `TushareFetcher`, add to
`BaseFetcher`'s rate-limit pool, never create a side channel.

## Step 5 — Compare and Decide

```python
def improved(prev, curr) -> str:
    wr_delta = curr["win_rate_pct"] - prev["win_rate_pct"]
    pf_drop  = (prev.get("profit_factor") or 0) - (curr.get("profit_factor") or 0)
    if wr_delta >= 2 and pf_drop <= 0:
        return "KEEP"
    if wr_delta < -1 or pf_drop > 0.2:
        return "REVERT"
    return "INCONCLUSIVE — try another lever"
```

Always print the side-by-side table:

```
              baseline   iteration_N
total_picks:      ...    ...
win_rate_pct:     ...    ...   (Δ +X.X)
profit_factor:    ...    ...   (Δ +X.X)
max_drawdown:     ...    ...
alpha_vs_csi300:  ...    ...
```

## Step 6 — Final Report

End with:

```
# EoD Picker Tuning — <YYYY-MM-DD HH:MM>

## Baseline → Best
| Metric | Baseline | Best (iter N) | Δ |
|---|---|---|---|
| win_rate_pct | ... | ... | ... |
| profit_factor | ... | ... | ... |
| max_drawdown_pct | ... | ... | ... |
| alpha_vs_csi300_pct | ... | ... | ... |
| total_picks | ... | ... | ... |

## Winning Change(s)
- iter 1: <lever> → kept (WR +X.X)
- iter 2: <lever> → reverted
- ...

## Recommendation to Persist
- Edit `src/services/picker/screener/eod_buyback.py` line N: `<old>` → `<new>`
- Or set env: `PICKER_*=<value>`

(Do NOT apply automatically. The user decides.)

## Open Questions / Data-Source Asks
- e.g. "本轮 stop_loss 占 60%，建议接入 Tushare moneyflow_hsgt 做北向资金过滤，是否同意？"
```

## Anti-Patterns

- **Don't change two levers per iteration** — you can't attribute the
  delta.
- **Don't extend the window when WR drops** to make the new run look
  better — the comparison is then meaningless.
- **Don't ignore profit_factor** — WR alone is gameable (small wins, big
  losses).
- **Don't run with `top_n != 2`** for this skill unless the user
  explicitly asks. The user spec is "每天 2 只".
- **Don't mark a 1pp WR move as success** with N < 50. Below 50 picks,
  noise band is roughly ±3pp.
- **Don't forget benchmark drift** — if CSI 300 dropped 10% in the
  window, a -3% strategy is actually +7% alpha. Use `alpha_vs_benchmark_pct`.
