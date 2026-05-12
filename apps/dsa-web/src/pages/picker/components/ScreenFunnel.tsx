import React from 'react';
import type { ScreenStats } from '../../../api/picker';

export const ScreenFunnel: React.FC<{ stats: ScreenStats }> = ({ stats }) => {
  const steps = [
    { label: '全市场', value: stats.total_stocks, color: 'bg-slate-300' },
    { label: '基本面', value: stats.after_basic_filter, color: 'bg-blue-400' },
    { label: '动量趋势', value: stats.after_momentum_filter, color: 'bg-cyan' },
    { label: '量价活跃', value: stats.after_volume_filter, color: 'bg-emerald-500' },
    { label: '精选池', value: stats.final_pool, color: 'bg-amber-500' },
  ];

  return (
    <div className="bg-card border border-border rounded-2xl p-8">
      <div className="flex items-center gap-2 mb-6">
        <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center">
          <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"/>
          </svg>
        </div>
        <h2 className="text-sm font-semibold text-primary">量化筛选漏斗</h2>
      </div>
      <div className="flex items-end gap-3">
        {steps.map((step, i) => {
          const maxVal = steps[0].value || 1;
          const ratio = Math.max(step.value / maxVal, 0.06);
          return (
            <React.Fragment key={step.label}>
              <div className="flex-1 flex flex-col items-center gap-2">
                <span className="text-lg font-bold text-primary tabular-nums">
                  {step.value.toLocaleString()}
                </span>
                <div
                  className={`w-full rounded-lg ${step.color} transition-all`}
                  style={{ height: `${Math.round(ratio * 120)}px`, minHeight: '8px' }}
                />
                <span className="text-xs font-medium text-secondary">{step.label}</span>
              </div>
              {i < steps.length - 1 && (
                <svg className="w-4 h-4 text-muted/40 shrink-0 mb-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
                </svg>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};

export default ScreenFunnel;
