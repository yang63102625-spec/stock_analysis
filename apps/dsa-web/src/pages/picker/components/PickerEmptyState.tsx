import React from 'react';
import { Spinner } from '../../../components/common';
import type { PickerHistoryItem } from '../../../api/picker';
import { FLOW_STEPS, PIPELINE_STEPS } from '../constants';
import { HistoryRow } from './HistoryRow';

export interface PickerEmptyStateProps {
  history: PickerHistoryItem[];
  historyTotal: number;
  historyLoading: boolean;
  historyVisibleCount: number;
  onShowMore: () => void;
  onSelect: (id: number) => void;
}

export const PickerEmptyState: React.FC<PickerEmptyStateProps> = ({
  history, historyTotal, historyLoading, historyVisibleCount, onShowMore, onSelect,
}) => (
  <div className="space-y-12">
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      {PIPELINE_STEPS.map((step) => (
        <div key={step.title}
             className="relative bg-card border border-border rounded-2xl p-8
                        hover:border-border-accent hover:shadow-md transition-all group overflow-hidden">
          <div className={`absolute top-0 left-0 right-0 h-1 bg-gradient-to-r ${step.color} opacity-60
                           group-hover:opacity-100 transition-opacity`} />
          <div className="flex items-center gap-3 mb-5">
            <div className={`w-12 h-12 rounded-2xl bg-gradient-to-br ${step.color} text-white
                            flex items-center justify-center shadow-sm`}>
              {step.icon}
            </div>
            <div>
              <span className="text-xs font-semibold text-cyan uppercase tracking-wider">{step.stage}</span>
              <h3 className="text-lg font-bold text-primary">{step.title}</h3>
            </div>
          </div>
          <ul className="space-y-2.5">
            {step.items.map((item) => (
              <li key={item} className="flex items-center gap-2.5 text-sm text-secondary">
                <svg className="w-4 h-4 text-cyan shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7"/>
                </svg>
                {item}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>

    <div className="flex items-center justify-center gap-4 flex-wrap">
      {FLOW_STEPS.map((item, i, arr) => (
        <React.Fragment key={item.sub}>
          <div className="text-center">
            <div className="text-xl font-bold text-primary">{item.label}</div>
            <div className="text-xs text-muted mt-0.5">{item.sub}</div>
          </div>
          {i < arr.length - 1 && (
            <svg className="w-5 h-5 text-muted/30 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
            </svg>
          )}
        </React.Fragment>
      ))}
    </div>

    <p className="text-center text-sm text-muted">
      点击上方按钮，开始两阶段智能选股分析
    </p>

    {history.length > 0 && (
      <div>
        <div className="flex items-center gap-2 mb-4">
          <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center">
            <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
          </div>
          <h2 className="text-sm font-semibold text-primary">
            历史筛选记录
            <span className="text-muted font-normal ml-1">({historyTotal})</span>
          </h2>
        </div>
        {historyLoading ? (
          <div className="flex justify-center py-8">
            <Spinner size="md" />
          </div>
        ) : (
          <div className="space-y-3">
            {history.slice(0, historyVisibleCount).map((item) => (
              <HistoryRow key={item.id} item={item} onSelect={onSelect} />
            ))}
            {history.length > historyVisibleCount && (
              <button
                onClick={onShowMore}
                className="w-full py-3 text-sm text-cyan hover:text-cyan/80
                           border border-border rounded-xl font-medium
                           hover:border-cyan/30 transition-colors"
              >
                加载更多（还有 {history.length - historyVisibleCount} 条）↓
              </button>
            )}
          </div>
        )}
      </div>
    )}
  </div>
);

export default PickerEmptyState;
