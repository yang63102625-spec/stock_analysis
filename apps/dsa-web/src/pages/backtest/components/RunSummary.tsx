import type React from 'react';
import type { BacktestRunResponse } from '../../../types/backtest';

export const RunSummary: React.FC<{ data: BacktestRunResponse }> = ({ data }) => (
  <div className="flex flex-wrap items-center gap-4 px-5 py-3 rounded-xl bg-card border border-border text-sm animate-fade-in">
    <span className="text-secondary">处理: <span className="text-primary font-semibold">{data.processed}</span></span>
    <span className="text-secondary">保存: <span className="text-cyan font-semibold">{data.saved}</span></span>
    <span className="text-secondary">完成: <span className="text-emerald-500 font-semibold">{data.completed}</span></span>
    <span className="text-secondary">数据不足: <span className="text-amber-500 font-semibold">{data.insufficient}</span></span>
    {data.errors > 0 && (
      <span className="text-secondary">错误: <span className="text-red-500 font-semibold">{data.errors}</span></span>
    )}
  </div>
);

export default RunSummary;
