import type React from 'react';
import type { BacktestResultItem } from '../../../types/backtest';
import { Pagination, Spinner } from '../../../components/common';
import { boolIcon, outcomeBadge, pct, statusBadge } from '../utils';

export interface AnalysisResultsTableProps {
  results: BacktestResultItem[];
  isLoading: boolean;
  totalResults: number;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export const AnalysisResultsTable: React.FC<AnalysisResultsTableProps> = ({
  results, isLoading, totalResults, currentPage, totalPages, onPageChange,
}) => {
  if (isLoading) {
    return (
      <div className="flex flex-col items-center py-20">
        <Spinner size="lg" />
        <p className="mt-6 text-sm text-secondary">加载回测结果...</p>
      </div>
    );
  }
  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center py-20 text-center">
        <div className="w-16 h-16 mb-4 rounded-2xl bg-elevated flex items-center justify-center">
          <svg className="w-7 h-7 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-primary mb-2">暂无回测数据</h3>
        <p className="text-sm text-muted max-w-md">
          系统会对历史分析记录进行回测验证。点击"运行回测"开始评估，或等待分析记录积累足够天数后自动生成。
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="bg-card border border-border rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-elevated/50">
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">代码</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">名称</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">分析日期</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">信号</th>
                <th className="px-4 py-3 text-right text-xs text-muted font-medium">量化分</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">策略</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">方向</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">结果</th>
                <th className="px-4 py-3 text-right text-xs text-muted font-medium">收益率</th>
                <th className="px-4 py-3 text-right text-xs text-muted font-medium">持仓</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">退出原因</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <tr
                  key={row.analysisHistoryId}
                  className="border-t border-border/50 hover:bg-surface-hover/50 transition-colors"
                >
                  <td className="px-4 py-2.5 font-mono text-cyan text-xs">{row.code}</td>
                  <td className="px-4 py-2.5 text-sm text-primary font-medium truncate max-w-[120px]" title={row.name || ''}>{row.name || '--'}</td>
                  <td className="px-4 py-2.5 text-xs text-secondary">{row.analysisDate || '--'}</td>
                  <td className="px-4 py-2.5 text-xs">
                    <span className="font-mono text-primary">{row.buySignalAtEval || '--'}</span>
                  </td>
                  <td className="px-4 py-2.5 text-sm font-mono text-right text-primary">
                    {row.signalScoreAtEval != null ? row.signalScoreAtEval : '--'}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-secondary">{row.strategyId || '--'}</td>
                  <td className="px-4 py-2.5 text-sm">
                    <span className="flex items-center gap-1.5">
                      {boolIcon(row.directionCorrect)}
                      <span className="text-muted text-xs">{row.directionExpected || ''}</span>
                    </span>
                  </td>
                  <td className="px-4 py-2.5">{outcomeBadge(row.outcome)}</td>
                  <td className="px-4 py-2.5 text-sm font-mono text-right">
                    <span className={
                      row.simulatedReturnPct != null
                        ? row.simulatedReturnPct > 0 ? 'text-red-600' : row.simulatedReturnPct < 0 ? 'text-emerald-600' : 'text-secondary'
                        : 'text-muted'
                    }>
                      {pct(row.simulatedReturnPct)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs font-mono text-right text-secondary">
                    {row.holdDays != null ? `${row.holdDays}d` : '--'}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-secondary" title={row.exitReason || ''}>
                    {row.exitReason || '--'}
                  </td>
                  <td className="px-4 py-2.5">{statusBadge(row.evalStatus)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted">共 {totalResults} 条记录</span>
        <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={onPageChange} />
      </div>
    </div>
  );
};

export default AnalysisResultsTable;
