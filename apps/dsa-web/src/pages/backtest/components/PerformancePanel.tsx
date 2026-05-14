import type React from 'react';
import type { PerformanceMetrics } from '../../../types/backtest';
import { pct } from '../utils';

const StatCell: React.FC<{ label: string; value: string; accent?: boolean }> = ({ label, value, accent }) => (
  <div className="flex flex-col items-center px-3 py-2">
    <span className={`text-lg font-bold font-mono tabular-nums ${accent ? 'text-cyan' : 'text-primary'}`}>{value}</span>
    <span className="text-xs text-muted mt-0.5 whitespace-nowrap">{label}</span>
  </div>
);

const BreakdownGrid: React.FC<{ metrics: PerformanceMetrics }> = ({ metrics }) => {
  const groups: Array<{ title: string; data?: Record<string, { total: number; win: number; loss: number; win_rate_pct?: number | null }> }> = [
    { title: '按信号', data: metrics.signalBreakdown as never },
    { title: '按量化分', data: metrics.scoreBucketBreakdown as never },
    { title: '按盈亏比', data: metrics.riskRewardBreakdown as never },
    { title: '按退出原因', data: metrics.exitReasonBreakdown as never },
    { title: '按大盘', data: metrics.regimeBreakdown as never },
    { title: '按策略', data: metrics.strategyBreakdown as never },
  ];
  const visible = groups.filter((g) => g.data && Object.keys(g.data).length > 0);
  if (visible.length === 0) return null;
  return (
    <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
      {visible.map((g) => (
        <div key={g.title} className="rounded-xl border border-border bg-elevated/40 p-3">
          <div className="text-xs text-muted mb-2">{g.title}</div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted">
                <th className="text-left font-normal pb-1">分桶</th>
                <th className="text-right font-normal pb-1">N</th>
                <th className="text-right font-normal pb-1">胜率</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(g.data!).map(([k, v]) => (
                <tr key={k} className="border-t border-border/40">
                  <td className="py-1 font-mono text-primary">{k}</td>
                  <td className="py-1 text-right font-mono text-secondary">{v.total}</td>
                  <td className="py-1 text-right font-mono">
                    <span className={
                      v.win_rate_pct == null ? 'text-muted'
                        : v.win_rate_pct >= 60 ? 'text-emerald-500'
                        : v.win_rate_pct >= 45 ? 'text-secondary'
                        : 'text-red-500'
                    }>
                      {v.win_rate_pct != null ? `${v.win_rate_pct.toFixed(0)}%` : '--'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
};

export const PerformancePanel: React.FC<{ metrics: PerformanceMetrics; title: string }> = ({ metrics, title }) => (
  <div className="bg-card border border-border rounded-2xl p-6">
    <div className="flex items-center gap-2 mb-5">
      <div className="w-8 h-8 rounded-lg bg-cyan/10 flex items-center justify-center">
        <svg className="w-4 h-4 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
        </svg>
      </div>
      <h2 className="text-sm font-semibold text-primary">{title}</h2>
      <span className="ml-auto text-xs text-muted font-mono">
        {Number(metrics.completedCount)} / {Number(metrics.totalEvaluations)} 已评估
        <span className="mx-2">·</span>
        <span className="text-emerald-500">{metrics.winCount}胜</span>
        {' / '}
        <span className="text-red-500">{metrics.lossCount}负</span>
        {' / '}
        <span className="text-amber-500">{metrics.neutralCount}平</span>
      </span>
    </div>
    <div className="space-y-2">
      <div className="text-[10px] text-muted px-1">信号层（AI 方向判断）</div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-1 divide-x divide-border/40">
        <StatCell label="方向准确率" value={pct(metrics.directionAccuracyPct)} accent />
        <StatCell label="信号胜率" value={pct(metrics.winRatePct)} />
        <StatCell label="股票收益" value={pct(metrics.avgStockReturnPct)} />
        <StatCell label="评估总数" value={String(metrics.completedCount)} />
      </div>
      <div className="text-[10px] text-muted px-1 pt-1">执行层（按 AI 计划严格成交）</div>
      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-7 gap-1 divide-x divide-border/40">
        <StatCell label="入场率" value={pct(metrics.fillRatePct)} accent />
        <StatCell label="交易胜率" value={pct(metrics.tradeWinRatePct)} accent />
        <StatCell label="期望值" value={pct(metrics.expectancyPct)} accent />
        <StatCell label="平均 R" value={metrics.avgRMultiple != null ? metrics.avgRMultiple.toFixed(2) : '--'} accent />
        <StatCell label="盈亏因子" value={metrics.profitFactor != null ? metrics.profitFactor.toFixed(2) : '--'} />
        <StatCell label="已成交" value={`${metrics.filledCount}/${metrics.filledCount + metrics.notFilledCount}`} />
        <StatCell label="涨停过滤" value={String(metrics.notFilledLimitUpCount)} />
      </div>
      <div className="text-[10px] text-muted px-1 pt-1">风险层（净值与歧义）</div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-1 divide-x divide-border/40">
        <StatCell label="最大回撤" value={pct(metrics.maxDrawdownPct)} />
        <StatCell label="平均 MAE" value={pct(metrics.avgMaePct)} />
        <StatCell label="平均 MFE" value={pct(metrics.avgMfePct)} />
        <StatCell label="同 bar 歧义" value={`${metrics.ambiguousCount} (${pct(metrics.ambiguousRate)})`} />
      </div>
    </div>
    <BreakdownGrid metrics={metrics} />
  </div>
);

export default PerformancePanel;
