import { useEffect } from 'react';
import type React from 'react';
import { ApiErrorAlert, Spinner } from '../../components/common';
import { usePickerBacktest } from './hooks/usePickerBacktest';
import { PickerBacktestPanel } from './components/PickerBacktestPanel';
import { PickerHistoryList } from './components/PickerHistoryList';
import { PickerResultsTable } from './components/PickerResultsTable';
import { StrategyChips } from './components/StrategyChips';

export interface PickerTabProps {
  active: boolean;
}

export const PickerTab: React.FC<PickerTabProps> = ({ active }) => {
  const p = usePickerBacktest();

  useEffect(() => {
    if (active) p.loadOnActivate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  return (
    <>
      <div className="card-elevated p-6 mb-8">
        <p className="text-xs text-muted mb-4">
          选股回测需逐日调用 Tushare 等数据源，日期较多时可能需 5–15 分钟，请耐心等待。
        </p>
        <div className="flex flex-col gap-3.5">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-5 gap-y-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted">开始日期</label>
              <input
                type="date"
                value={p.startDate}
                onChange={(e) => p.setStartDate(e.target.value)}
                disabled={p.running}
                className="w-full px-3 py-2 rounded-lg bg-card border border-border
                           text-sm text-primary
                           focus:outline-none focus:border-cyan/50 focus:ring-2 focus:ring-cyan/20 transition-all"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted">结束日期</label>
              <input
                type="date"
                value={p.endDate}
                onChange={(e) => p.setEndDate(e.target.value)}
                disabled={p.running}
                className="w-full px-3 py-2 rounded-lg bg-card border border-border
                           text-sm text-primary
                           focus:outline-none focus:border-cyan/50 focus:ring-2 focus:ring-cyan/20 transition-all"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted">持仓天数(天)</label>
              <input
                type="number"
                min={1}
                max={60}
                value={p.holdDays}
                onChange={(e) => p.setHoldDays(e.target.value)}
                disabled={p.running}
                className="w-full px-3 py-2 rounded-lg bg-card border border-border
                           text-sm text-primary text-center
                           focus:outline-none focus:border-cyan/50 focus:ring-2 focus:ring-cyan/20 transition-all"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted">每日只数(只)</label>
              <input
                type="number"
                min={1}
                max={20}
                value={p.topN}
                onChange={(e) => p.setTopN(e.target.value)}
                disabled={p.running}
                className="w-full px-3 py-2 rounded-lg bg-card border border-border
                           text-sm text-primary text-center
                           focus:outline-none focus:border-cyan/50 focus:ring-2 focus:ring-cyan/20 transition-all"
              />
            </div>
          </div>

          <div className="flex items-center justify-between gap-4">
            <StrategyChips
              label="选股策略"
              value={p.strategies}
              onChange={p.setStrategies}
              disabled={p.running}
            />
            <button
              type="button"
              onClick={p.handleRun}
              disabled={p.running}
              className="h-[42px] px-6 rounded-lg bg-gradient-to-r from-cyan to-cyan-dim text-white
                         font-semibold text-[13px] hover:shadow-lg transition-all whitespace-nowrap shrink-0
                         disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {p.running ? (
                <>
                  <Spinner size="sm" className="border-white/30 border-t-white shrink-0" />
                  <span title="约 5–15 分钟">回测中…</span>
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                  </svg>
                  <span>运行选股回测</span>
                </>
              )}
            </button>
          </div>
        </div>
        {p.error && <ApiErrorAlert error={p.error} className="mt-4" />}
      </div>

      <PickerHistoryList items={p.history} onSelect={p.handleLoadHistoryDetail} />

      {p.result?.summary && (
        <div className="mb-8">
          <PickerBacktestPanel summary={p.result.summary} />
        </div>
      )}

      {p.result?.results && <PickerResultsTable results={p.result.results} />}
    </>
  );
};

export default PickerTab;
