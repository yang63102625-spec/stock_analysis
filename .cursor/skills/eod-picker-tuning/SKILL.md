---
name: eod-picker-tuning
description: 迭代优化 eod_buyback（尾盘买入）选股策略的回测胜率。每天 top_n=2，跑近 90 个交易日窗口，按 exit_reason + 市场环境诊断失败模式，每轮只调一个变量并给出 A 股交易学解释，重跑后对比胜率/盈亏比/回撤/Alpha，每轮生成 markdown 报告。当用户提到 "提高选股回测胜率" / "优化尾盘策略" / "跑尾盘选股回测" / "tune eod_buyback" 等时使用。任何新增 Tushare 数据源都必须先征求用户同意。
disable-model-invocation: true
---

# 尾盘买入策略回测调优循环

迭代优化 `eod_buyback` 策略：跑回测 → 诊断弱点 → 单变量改动 → 重跑 → 对比，每轮产出 md 报告。

## 硬性规则

- **绝不**静默删除 `picker_backtest_history` 行 — 它是实验台账。如果某次旧跑结果误导，重命名/标注，不要删。
- **绝不**未经用户明确同意就把参数写进 `.env` 或 `config_registry`。提议只修改下一轮 in-memory 请求载荷。
- **绝不**未经用户同意就接入新的 Tushare endpoint / AkShare API / 其他数据源。用户有 Tushare 8000 积分≠所有 endpoint 都欢迎。
- **绝不**对 `total_picks < 20` 的样本宣称胜率提升。低于 20 任何 delta 都是噪声。
- **绝不**用 `--no-notify`。本 skill 不碰 `main.py`，回测直接走 `PickerBacktestService`。
- **每轮必出 md 报告**写入 `reports/eod_tuning/iter_<N>_<YYYYMMDD_HHMM>.md`，方便用户直接看进展。

## "胜率"的定义

`PickerBacktestSummary.win_rate_pct = win_count / (win_count + loss_count) * 100`

`simulate_forward_trade` 退出时 `return_pct > 0` 即为 win。`insufficient`（无 forward bar）从分子分母都剔除。

胜率必须配以下指标一起看：
- `avg_return_pct` — 高胜率但负均值收益 = 小赚大亏（不对称尾部）
- `profit_factor` — `sum_wins / |sum_losses|`。<1 即使 WR>50% 也是亏钱系统
- `max_drawdown_pct` — 时间序列净值复利最大回撤
- `alpha_vs_benchmark_pct` — 同窗口 vs 沪深 300

任何"改进"必须 **WR↑ AND profit_factor 不降**。

## 迭代循环

```
迭代 N：
- [ ] 跑 baseline（或上一轮最优）
- [ ] 解析 summary + 每条 pick 结果
- [ ] 诊断 top 失败模式
- [ ] 提议一个改动（一个变量！）+ 交易学理由
- [ ] AskQuestion 取得用户确认
- [ ] 用改动重跑
- [ ] 对比 WR/PF/回撤
- [ ] 写 md 报告
- [ ] 决策：保留 / 撤回 / 继续
```

**停止条件（任一）：**
1. 连续两轮 WR 提升 < 2pp
2. profit_factor 跌破上一轮最优
3. 用户说停
4. 同一参数家族连改两次都没改进 — 死路，换或停

## Step 0 — 前置检查

```bash
cd /Users/wei/Projects/tw/stock_analysis
ls .env .venv/bin/python > /dev/null && echo "env ok"
.venv/bin/python -c "from src.services.picker_backtest_service import PickerBacktestService; print('import ok')"
mkdir -p reports/eod_tuning
```

import 失败立即停，修基础设施不在本 skill 范围。

## Step 1 — Baseline

近 **90 个自然日**到最近一个交易日，保持市场制度相关性。需要更长用户会说。

```bash
.venv/bin/python <<'EOF'
from datetime import date, timedelta
import json
from src.services.picker_backtest_service import PickerBacktestService

today = date.today()
end = today.strftime("%Y%m%d")
start = (today - timedelta(days=90)).strftime("%Y%m%d")

svc = PickerBacktestService()
res = svc.run(
    start_date=start, end_date=end,
    hold_days=10, top_n=2,
    picker_strategies=["eod_buyback"],
)
# 保存原始结果便于后续分析
with open("reports/eod_tuning/_last_run.json", "w") as f:
    json.dump(res, f, ensure_ascii=False, default=str, indent=2)
print("=== Summary ===")
s = res.get("summary") or {}
for k in ("total_picks","win_count","loss_count","insufficient_count",
         "win_rate_pct","avg_return_pct","profit_factor",
         "max_drawdown_pct","alpha_vs_benchmark_pct"):
    print(f"  {k}: {s.get(k)}")
print(f"  trade_dates_count: {res.get('trade_dates_count')}")
EOF
```

如果 `total_picks < 20`，**把窗口扩到 180 天**再诊断。

## Step 2 — 诊断 top 失败模式

按 `exit_reason` 分桶 losers：
- `stop_loss` 多 → 入场质量差，过滤太宽松
- `window_end` 多且收益负 → 没爆发力，"死钱"，动量/量能门槛太低
- `trailing_ma10` 小幅负 → 多为接近平手，常是市场环境错配（弱市运行）

按市场环境分桶：
- losers 集中在 `bear / strong_bear` → 加 market guard（已有，确认是否启用）
- 均匀分布 → 策略本身问题，不是环境

## Step 3 — 提议一个改动（必须给交易学理由）

**杠杆菜单：每轮只选 1 项。**

| 杠杆 | 位置 | A 股交易学理由 |
|---|---|---|
| `change_pct` 上限 6% → 5% | `eod_buyback.py:146` | 收盘 +5% 以上常为冲高诱多，次日跳空回落概率大 |
| 换手率下限 5% → 7% | line 158 | 换手 <7% 配合 +3-6% 涨幅，资金参与度不足，假信号 |
| 市值下限 60亿 → 80亿 | line 183 | 60亿以下易被游资拉抬制造假信号，机构难进难出 |
| 市值上限 300亿 → 200亿 | line 183 | 300亿以上尾盘异动多为指数资金推动，无个股 alpha |
| 加 5 日均线斜率向上过滤 | 新逻辑 | 截图式买入易踩反弹中继；ma5 必须上行 |
| 加前一日非涨停过滤 | 新逻辑 | 涨停次日 +3-6% 多为出货，胜率显著低 |
| `hold_days` 10 → 5 | run 参数 | 尾盘是短线策略，10 天太长，趋势衰减后命中率降 |
| 加北向净流入过滤（需 `moneyflow_hsgt`） | 新数据源 | **需先问用户**是否同意接 Tushare moneyflow_hsgt |
| 加主力净流入过滤（需 `moneyflow`） | 新数据源 | **需先问用户** |
| 加龙虎榜机构净买入加分（需 `top_list`） | 新数据源 | **需先问用户** |

**绝不一轮改两个变量** — 否则归因失败。

## Step 4 — 确认 + 重跑

用 `AskQuestion`：
- title: "下一轮回测调整"
- prompt: "本轮提议：<change>。理由：<rationale>。预期：WR <baseline> → <target>。"
- options: `apply` / `different` / `add_data`（仅当涉及新数据源） / `stop`

**改阈值的方式**（`change_pct / 换手率 / 市值` 等是 .py 文件里的常量）：
1. 直接改 `src/services/picker/screener/eod_buyback.py` 对应行
2. 跑回测
3. 对比完写完报告后**立即 `git checkout` 该文件**还原（除非用户最终决定保留）
4. md 报告里明确记录"临时改动 line N: X → Y，已还原"

**新数据源**：必须 `AskQuestion` `add_data` 选项明确同意；遵守 `data-source-priority.mdc`，扩展 `TushareFetcher`，复用 `BaseFetcher` 限流，禁开侧通道。

## Step 5 — 对比决策

```python
def verdict(prev, curr):
    wr_d = curr["win_rate_pct"] - prev["win_rate_pct"]
    pf_drop = (prev.get("profit_factor") or 0) - (curr.get("profit_factor") or 0)
    if wr_d >= 2 and pf_drop <= 0: return "KEEP"
    if wr_d < -1 or pf_drop > 0.2: return "REVERT"
    return "INCONCLUSIVE — 换杠杆"
```

## Step 6 — Markdown 报告（每轮必出）

写入 `reports/eod_tuning/iter_<N>_<YYYYMMDD_HHMM>.md`：

```markdown
# 尾盘买入策略调优 — 第 N 轮

- 时间：YYYY-MM-DD HH:MM
- 窗口：YYYYMMDD ~ YYYYMMDD（X 个交易日）
- 持仓：10 天，每日 top 2

## 本轮改动

| 杠杆 | 旧值 | 新值 | 理由 |
|---|---|---|---|
| change_pct 上限 | 6.0 | 5.0 | 收盘冲高 5%+ 常诱多... |

> 临时改动：`src/services/picker/screener/eod_buyback.py:146`，已 `git checkout` 还原

## 关键指标对比

| 指标 | Baseline | 本轮 | Δ |
|---|---|---|---|
| total_picks | ... | ... | ... |
| win_rate_pct | ... | ... | +X.X |
| avg_return_pct | ... | ... | ... |
| profit_factor | ... | ... | ... |
| max_drawdown_pct | ... | ... | ... |
| alpha_vs_csi300_pct | ... | ... | ... |

## 失败模式分布（loser 按 exit_reason）

| exit_reason | 数量 | 占比 | 平均收益 |
|---|---|---|---|
| stop_loss | 12 | 35% | -7.8% |
| window_end | 18 | 53% | -2.1% |
| trailing_ma10 | 4 | 12% | -0.6% |

## 5 个最差 loser

| 日期 | 代码 | 名称 | 入场 | 出场 | 收益 | 退出 | 持仓 |
|---|---|---|---|---|---|---|---|
| ... |

## 结论

**判定**：KEEP / REVERT / INCONCLUSIVE

**下一步建议杠杆**：<下一轮想试什么 + 理由>

**待用户确认事项**：
- 是否同意接入 Tushare `moneyflow_hsgt`（积分 ok 但属于新依赖）？
```

报告写完，在对话里**给用户报告路径 + 一句话总结**，再 `AskQuestion` 决定下一步。

## 终局报告

整个迭代结束后产出 `reports/eod_tuning/SUMMARY_<YYYYMMDD>.md`：

```markdown
# 尾盘策略调优总结

## Baseline → Best
| 指标 | Baseline | Best (iter N) | Δ |
|---|---|---|---|

## 保留的改动
- iter 1: <杠杆> → KEEP（WR +X.X）
- iter 3: <杠杆> → KEEP

## 撤回的改动
- iter 2: <杠杆> → REVERT（PF 跌 0.3）

## 建议持久化
- 编辑 `src/services/picker/screener/eod_buyback.py:146` 6.0 → 5.0
- 或 env: PICKER_*=...

(不自动应用，用户决定)

## 后续待办 / 数据源建议
- ...
```

## 反模式

- **不要一轮改两个变量** — 归因失败
- **不要在 WR 跌时扩窗口**让结果好看 — 对比就废了
- **不要忽略 profit_factor** — WR 单看可被小赢大亏游戏化
- **不要用 top_n != 2** — 用户规格就是每天 2 只
- **不要把 1pp 的 WR 移动当成功** — N < 50 时噪声带 ±3pp
- **不要忘记基准** — 沪深 300 跌 10% 时，策略 -3% 实际是 +7% alpha；用 `alpha_vs_benchmark_pct`
