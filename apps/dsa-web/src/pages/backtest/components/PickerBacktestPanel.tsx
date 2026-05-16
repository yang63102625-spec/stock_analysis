import type React from 'react';
import type { PickerBacktestSummary } from '../../../types/pickerBacktest';

const StatCell: React.FC<{ label: string; value: string; accent?: boolean }> = ({ label, value, accent }) => (
  <div className="flex flex-col items-center px-3 py-2">
    <span className={`text-lg font-bold font-mono tabular-nums ${accent ? 'text-cyan' : 'text-primary'}`}>{value}</span>
    <span className="text-xs text-muted mt-0.5 whitespace-nowrap">{label}</span>
  </div>
);

export const PickerBacktestPanel: React.FC<{ summary: PickerBacktestSummary }> = ({ summary }) => (
  <div className="bg-card border border-border rounded-2xl p-6">
    <div className="flex items-center gap-2 mb-5">
      <div className="w-8 h-8 rounded-lg bg-cyan/10 flex items-center justify-center">
        <svg className="w-4 h-4 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
        </svg>
      </div>
      <h2 className="text-sm font-semibold text-primary">选股回测表现</h2>
      <span className="ml-auto text-xs text-muted font-mono">
        {summary.tradeDatesWithPicks != null && (
          <span className="text-secondary mr-2">有候选 {summary.tradeDatesWithPicks} 天</span>
        )}
        {summary.winCount}胜 / {summary.lossCount}负 / {summary.insufficientCount}数据不足
      </span>
    </div>
    <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-9 gap-1 divide-x divide-border/40">
      <StatCell label="胜率" value={summary.winRatePct != null ? `${summary.winRatePct.toFixed(1)}%` : '--'} accent />
      <StatCell label="平均收益" value={summary.avgReturnPct != null ? `${summary.avgReturnPct.toFixed(1)}%` : '--'} accent />
      <StatCell label="最大回撤" value={summary.maxDrawdownPct != null ? `${summary.maxDrawdownPct.toFixed(1)}%` : '--'} />
      <StatCell label="盈亏比" value={summary.profitFactor != null ? summary.profitFactor.toFixed(2) : '--'} />
      <StatCell label="超额收益" value={summary.alphaVsBenchmarkPct != null ? `${summary.alphaVsBenchmarkPct.toFixed(1)}%` : '--'} />
      <StatCell label="基准收益" value={summary.benchmarkAvgReturnPct != null ? `${summary.benchmarkAvgReturnPct.toFixed(1)}%` : '--'} />
      <StatCell label="年化收益" value={summary.cagrPct != null ? `${summary.cagrPct.toFixed(1)}%` : '--'} accent />
      <StatCell label="Sharpe" value={summary.sharpeRatio != null ? summary.sharpeRatio.toFixed(2) : '--'} />
      <StatCell label="Calmar" value={summary.calmarRatio != null ? summary.calmarRatio.toFixed(2) : '--'} />
    </div>
  </div>
);

export default PickerBacktestPanel;
