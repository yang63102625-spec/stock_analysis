import type React from 'react';
import type { PickerBacktestResultItem } from '../../../types/pickerBacktest';
import { outcomeBadge } from '../utils';

export interface PickerResultsTableProps {
  results: PickerBacktestResultItem[];
}

export const PickerResultsTable: React.FC<PickerResultsTableProps> = ({ results }) => {
  if (results.length === 0) return null;
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="bg-card border border-border rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-elevated/50">
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">日期</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">代码</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">名称</th>
                <th className="px-4 py-3 text-right text-xs text-muted font-medium">买入价</th>
                <th className="px-4 py-3 text-right text-xs text-muted font-medium">收益率</th>
                <th className="px-4 py-3 text-right text-xs text-muted font-medium">持仓</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">退出原因</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">策略</th>
                <th className="px-4 py-3 text-left text-xs text-muted font-medium">结果</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row, idx) => (
                <tr
                  key={`${row.tradeDate}-${row.code}-${idx}`}
                  className="border-t border-border/50 hover:bg-surface-hover/50 transition-colors"
                >
                  <td className="px-4 py-2.5 text-xs text-secondary">{row.tradeDate}</td>
                  <td className="px-4 py-2.5 font-mono text-cyan text-xs">{row.code}</td>
                  <td className="px-4 py-2.5 text-sm text-primary truncate max-w-[120px]" title={row.name || ''}>{row.name || '--'}</td>
                  <td className="px-4 py-2.5 text-sm font-mono text-right">{row.entryPrice?.toFixed(2) ?? '--'}</td>
                  <td className="px-4 py-2.5 text-sm font-mono text-right">
                    <span className={
                      row.returnPct != null
                        ? row.returnPct > 0 ? 'text-red-600' : row.returnPct < 0 ? 'text-emerald-600' : 'text-secondary'
                        : 'text-muted'
                    }>
                      {row.returnPct != null ? `${row.returnPct.toFixed(1)}%` : '--'}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs font-mono text-right text-secondary">
                    {row.holdDays != null ? `${row.holdDays}d` : '--'}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-secondary" title={row.exitReason || ''}>
                    {row.exitReason || '--'}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-secondary">{row.strategyId || '--'}</td>
                  <td className="px-4 py-2.5">{outcomeBadge(row.outcome)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default PickerResultsTable;
