import type React from 'react';
import { STRATEGY_LABELS } from '../../../api/picker';
import type { PickerBacktestHistoryItem } from '../../../types/pickerBacktest';

export interface PickerHistoryListProps {
  items: PickerBacktestHistoryItem[];
  onSelect: (id: number) => void;
}

export const PickerHistoryList: React.FC<PickerHistoryListProps> = ({ items, onSelect }) => {
  if (items.length === 0) return null;
  return (
    <div className="mb-8">
      <h3 className="text-sm font-medium text-muted mb-3">历史记录</h3>
      <div className="flex flex-wrap gap-2">
        {items.map((h) => (
          <button
            key={h.id}
            type="button"
            onClick={() => onSelect(h.id)}
            className="px-3 py-2 rounded-lg bg-elevated border border-border text-xs text-secondary
                       hover:border-cyan/40 hover:text-primary transition-all text-left"
          >
            <span className="font-mono">{h.startDate}–{h.endDate}</span>
            <span className="mx-1.5 text-muted">|</span>
            <span>{h.holdDays}d×{h.topN}</span>
            {(h.pickerStrategies && h.pickerStrategies.length > 0) ? (
              <span className="mx-1.5 text-muted">
                {h.pickerStrategies.map((s) => STRATEGY_LABELS[s] ?? s).join('、')}
              </span>
            ) : (
              <span className="mx-1.5 text-muted">{STRATEGY_LABELS['buy_pullback']}</span>
            )}
            {h.winRatePct != null && (
              <span className="ml-1.5 text-cyan">{h.winRatePct.toFixed(1)}%</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
};

export default PickerHistoryList;
