import type React from 'react';
import { ApiErrorAlert, Spinner } from '../../components/common';
import { useAnalysisBacktest } from './hooks/useAnalysisBacktest';
import { PerformancePanel } from './components/PerformancePanel';
import { RunSummary } from './components/RunSummary';
import { AnalysisResultsTable } from './components/AnalysisResultsTable';

export const AnalysisTab: React.FC = () => {
  const a = useAnalysisBacktest();

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') a.handleFilter();
  };

  return (
    <>
      <div className="card-elevated p-6 mb-8 space-y-3">
        <div className="text-xs text-muted">
          回测严格按每条 AI 推荐自带的买入价 / 止损 / 止盈在历史 K 线上模拟执行（含 0.05% 滑点 + 0.075% 单边手续费 + 涨停过滤；同 bar 双触发取止损保守口径）。
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={a.codeFilter}
            onChange={(e) => a.setCodeFilter(e.target.value.toUpperCase())}
            onKeyDown={onKeyDown}
            placeholder="股票代码（留空查看全部）"
            disabled={a.isRunning}
            className="flex-1 min-w-[180px] px-4 py-2.5 rounded-xl bg-elevated border border-border
                       text-sm text-primary placeholder:text-muted
                       focus:outline-none focus:border-cyan/40 focus:ring-1 focus:ring-cyan/20 transition-all"
          />
          <div className="flex items-center gap-2">
            <span className="text-sm text-secondary">窗口</span>
            <input
              type="number"
              min={1}
              max={120}
              value={a.evalDays}
              onChange={(e) => a.setEvalDays(e.target.value)}
              placeholder="10"
              disabled={a.isRunning}
              className="w-16 px-3 py-2.5 rounded-xl bg-elevated border border-border
                         text-sm text-primary text-center
                         focus:outline-none focus:border-cyan/40 focus:ring-1 focus:ring-cyan/20 transition-all"
            />
            <span className="text-xs text-muted">天</span>
          </div>
          <button
            type="button"
            onClick={() => a.setForceRerun(!a.forceRerun)}
            disabled={a.isRunning}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium
              transition-all border cursor-pointer
              ${a.forceRerun
                ? 'border-cyan/40 bg-cyan/10 text-cyan'
                : 'border-border bg-elevated text-muted hover:border-border-accent hover:text-secondary'}
              disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <span className={`w-2 h-2 rounded-full transition-colors ${a.forceRerun ? 'bg-cyan' : 'bg-muted/30'}`} />
            强制重算
          </button>
          <button
            type="button"
            onClick={a.handleFilter}
            disabled={a.isLoadingResults}
            className="px-5 py-2.5 rounded-xl bg-elevated border border-border text-sm font-medium
                       text-secondary hover:text-primary hover:border-border-accent transition-all"
          >
            筛选
          </button>
          <button
            type="button"
            onClick={a.handleRun}
            disabled={a.isRunning}
            className="h-[42px] px-6 rounded-lg bg-gradient-to-r from-cyan to-cyan-dim text-white
                       font-semibold text-[13px] hover:shadow-lg transition-all
                       disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {a.isRunning ? (
              <>
                <Spinner size="sm" className="border-white/30 border-t-white" />
                <span>回测中...</span>
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <span>运行回测</span>
              </>
            )}
          </button>
        </div>
        {a.runResult && <div className="mt-4"><RunSummary data={a.runResult} /></div>}
        {a.runError && <ApiErrorAlert error={a.runError} className="mt-4" />}
      </div>

      {(a.overallPerf || a.isLoadingPerf) && (
        <div className="space-y-4 mb-8">
          {a.isLoadingPerf ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size="lg" />
            </div>
          ) : (
            <>
              {a.overallPerf && <PerformancePanel metrics={a.overallPerf} title="整体表现" />}
              {a.stockPerf && <PerformancePanel metrics={a.stockPerf} title={a.stockPerf.code || a.codeFilter} />}
            </>
          )}
        </div>
      )}

      {a.pageError && <ApiErrorAlert error={a.pageError} className="mb-6" />}

      <AnalysisResultsTable
        results={a.results}
        isLoading={a.isLoadingResults}
        totalResults={a.totalResults}
        currentPage={a.currentPage}
        totalPages={a.totalPages}
        onPageChange={a.handlePageChange}
      />
    </>
  );
};

export default AnalysisTab;
