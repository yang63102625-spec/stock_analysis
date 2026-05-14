---
name: stock-runtime-check
description: Live runtime smoke test for the tw/stock_analysis project. Launches the CLI and API server, exercises picker / backtest / single-stock analysis / market review / agent Q&A, scans logs for errors and reports a structured summary. Use when the user explicitly asks to "跑一下自检", "启动起来跑一遍", "smoke test", "runtime check", or wants live functional verification of the running system. Distinct from generic code self-review — this one actually executes the program.
---

# Stock Runtime Smoke Check

End-to-end live verification for `/Users/wei/Projects/tw/stock_analysis`. Launches each major feature, watches logs for warnings / errors / tracebacks, and reports a structured findings list.

## Hard Rules (read first)

- **Never read, log, write or commit secrets.** `.env`, API keys, admin password — all off-limits to print or persist. If a step needs a credential, ask the user inline for that one run only and discard immediately (see Step 6 auth handling).
- **Never modify project code during the check.** This skill is observational. Surface issues, let the user decide.
- **Never send notifications.** Always pass `--no-notify` so WeChat / Feishu / Telegram stay quiet during smoke tests. If you observe a notification still being sent, that itself is a finding.
- **Never run with `--debug`** unless step 7 logs are inconclusive — debug log floods bury real issues.

## Preconditions (Step 0)

```bash
cd /Users/wei/Projects/tw/stock_analysis
ls -la .env .venv/bin/python && lsof -i :8000 || true
```

- Working directory: `/Users/wei/Projects/tw/stock_analysis`.
- Interpreter: **always `.venv/bin/python`**, never system `python3`. Wrong interpreter triggers `ModuleNotFoundError` and invalidates all later steps.
- `.env` exists and readable.
- Port 8000: free, OR holding a stale `main.py --serve-only` / `webui.py` from earlier — kill it (`kill <pid>; sleep 2; lsof -i :8000 || echo free`). Don't try to "fix" the env beyond that.
- Logs go to `logs/<prefix>_YYYYMMDD.log` and `logs/<prefix>_debug_YYYYMMDD.log`.

## Workflow

Track progress; tick as you go:

```
- [ ] 0. Preconditions
- [ ] 1. Quick CLI dry-run
- [ ] 2. Single-stock analysis (1 ticker, --no-notify, --no-market-review)
- [ ] 3. Picker (--picker-only --no-notify)
- [ ] 4. Backtest (--backtest --backtest-code <code> --backtest-force)
- [ ] 5. Market review (--market-review --no-notify)  [skip if Step 1 already ran it]
- [ ] 6. API server boot + auth probe + (optional) authenticated Q&A
- [ ] 7. Log scan + structured report
```

### Step 1: Quick CLI dry-run
```bash
.venv/bin/python main.py --dry-run --no-notify --stocks 600519 2>&1 | tail -40
```
Expected: exit 0, no traceback. Note: in this project `--dry-run` may still trigger market review + auto backtest tail jobs — that is current behavior, not a bug.

### Step 2: Single-stock analysis (real LLM call)
```bash
.venv/bin/python main.py --no-notify --stocks 600519 --workers 1 --no-market-review 2>&1 | tail -40
```
Watch for:
- `[ERROR]` lines (real ones — see "False positives" below)
- repeated rate-limit / timeout warnings from any single data source
- `Analyzer ... is_available=False` → flag LLM key issue
- `ResourceWarning: unclosed event loop` at end → known cleanup gap, low severity

### Step 3: Picker (AI stock selection)
```bash
.venv/bin/python main.py --picker-only --no-notify 2>&1 | tail -80
```
Watch for:
- screener pipeline stages each emitting `passed N stocks`
- `quantitative_filter` / `risk_filter` / `_backtest_score_mixin` import errors → recent refactor regression
- empty final pool with no reason logged → suspicious
- **Any push notification despite `--no-notify`** → finding (`--no-notify` was historically not honored on this code path)

### Step 4: Backtest
```bash
.venv/bin/python main.py --backtest --backtest-code 600519 --backtest-days 30 --backtest-force --no-notify 2>&1 | tail -40
```
Watch for:
- `processed=0` while you passed an explicit code → either no historical analysis row exists for that code with sufficient eval window, or CLI args dropped. Cross-check `data/stock_analysis.db` `analysis_history` table before declaring a bug. Note this in the report — it is a frequent UX papercut, not always a defect.
- `DataFrame empty` after `validate_ohlcv_dataframe` → real data source issue
- absurd returns (>500%, <-90%) → calc bug

### Step 5: Market review
Only if Step 1 didn't already run it (check Step 1 tail):
```bash
.venv/bin/python main.py --market-review --no-notify 2>&1 | tail -50
```
Watch `_market_prompt_builder` errors and missing index quotes.

### Step 6: API server + auth + agent Q&A

#### 6a. Boot
```bash
nohup .venv/bin/python webui.py > /tmp/dsa_webui.log 2>&1 &
WEBUI_PID=$!
sleep 8
lsof -i :8000 | head -3
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
```
Validate envelope: `{"code":0,"message":"success","data":{...},"timestamp":"..."}` per `project-patterns.mdc` §1.

#### 6b. Auth probe
```bash
curl -s http://127.0.0.1:8000/api/v1/auth/status | python3 -m json.tool
```

If `data.authEnabled == true && data.loggedIn == false`, choose one path:

**Path A — skip authenticated checks (default for unattended runs).**
Verify the unauthenticated endpoint returns the correct envelope error:
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" -d '{"message":"x"}' | python3 -m json.tool
```
Expect `{"code":1003,"message":"Login required",...}`. This still validates the envelope contract; mark Step 6 as `PARTIAL` in the report.

**Path B — ask the user for one-shot credentials.**
Tell the user: "Step 6 needs a logged-in session. Paste your admin password (used only this run, never logged or saved)." Then:
```bash
COOKIE_JAR=$(mktemp -t dsa_smoke_XXXXXX)
trap "rm -f $COOKIE_JAR" EXIT INT TERM
read -rs PASSWORD   # never expand $PASSWORD anywhere except the curl below
curl -s -c "$COOKIE_JAR" -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"$PASSWORD\"}" >/dev/null
unset PASSWORD
curl -s -b "$COOKIE_JAR" -X POST http://127.0.0.1:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"贵州茅台 600519 一句话最近表现"}' | python3 -m json.tool
```
Hard rules for Path B:
- Do NOT echo `$PASSWORD` back to the terminal, do NOT include it in any tool input or report.
- Do NOT write the password into any log, file, or commit.
- Do NOT cache the cookie jar beyond this run — `trap` removes it on exit.
- Validate response envelope structure even if `data.success == false`; an envelope-shape failure is itself a finding.

#### 6c. Tear down
```bash
kill $WEBUI_PID 2>/dev/null
wait $WEBUI_PID 2>/dev/null
rm -f "$COOKIE_JAR" 2>/dev/null
```

### Step 7: Log scan
```bash
TODAY=$(date +%Y%m%d)
echo "=== ERROR / Traceback ==="
grep -E "^[0-9-]+ [0-9:]+ \| ERROR" logs/stock_analysis_${TODAY}.log /tmp/dsa_webui.log 2>/dev/null | sort -u | head -30
echo "=== WARNING (top 20 unique) ==="
grep -E "WARNING" logs/stock_analysis_${TODAY}.log 2>/dev/null \
  | sed -E 's|.*WARNING +\| ||' | sort | uniq -c | sort -rn | head -20
```

Note the regex anchors `^[0-9-]+ [0-9:]+ \| ERROR` — this rejects false positives where the literal string `ERROR` appears inside a captured LLM/HTTP request body (very common in this project's debug stream).

#### False positives to ignore
- `'frequency_penalty': None` and similar inside captured `LiteLLM Params passed to completion()` payloads — that's the LLM SDK echoing its own argspec, not a real error.
- `DeprecationWarning: pkg_resources` from `lark_oapi` — third-party noise, harmless.
- One-off `Connection aborted` / `RemoteDisconnected` from a single data source if the next fetcher in the chain succeeded.

## Reporting Format

End with one structured report. Use this template verbatim:

```
# Runtime Self-Check Report — <YYYY-MM-DD HH:MM>

## Summary
- Steps run: N/7  (mark PARTIAL where auth was skipped)
- Status: PASS | PASS WITH WARNINGS | FAIL
- Total errors: <count> | Total warnings: <count>

## Per-Feature Result
| Step | Feature | Status | Notes |
|------|---------|--------|-------|
| 1 | dry-run | OK | - |
| 2 | single-stock analysis | OK | - |
| 3 | picker | WARN | --no-notify ignored: feishu push fired |
| 4 | backtest | INFO | processed=0, no historical row for 600519 within window |
| 5 | market review | OK | (covered by Step 1) |
| 6 | API + agent Q&A | PARTIAL | health envelope OK; chat skipped (auth) |

## Issues Found
1. **[severity]** <short title>
   - Where: `<file>:<line>` or `<METHOD path>`
   - Symptom: `<one-line log excerpt>`
   - Likely cause: <reasoned guess>
   - Suggested fix: <concise>

## Notes / False Positives Filtered
- <e.g. "transient akshare 502, retried OK">
```

Severity scale:
- `critical` — broke a feature outright
- `high` — degraded behavior or violated a documented contract (e.g. `--no-notify` ignored, envelope shape wrong)
- `medium` — warning that points at real but contained issue
- `low` — cosmetic / known noise

## Anti-Patterns

- Don't aggregate `WARN` as `FAIL` unless the warning actually broke a feature (e.g. all data sources down → picker can't run).
- Don't read `.env` to "find the password". If Step 6b needs auth, follow Path A or ask the user.
- Don't grep for unanchored "ERROR" — half the matches will be debug payloads (see Step 7 regex).
- Don't skip Step 0. Wrong interpreter / leaked port / missing `.env` invalidates everything below.
- Don't auto-run `git commit` even if findings are clean. The user decides.
