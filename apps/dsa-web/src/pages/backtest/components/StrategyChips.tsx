import type React from 'react';
import type { PickerStrategy } from '../../../types/pickerBacktest';
import { STRATEGY_OPTIONS } from '../utils';

export interface StrategyChipsProps {
  label: string;
  value: PickerStrategy[];
  onChange: (next: PickerStrategy[]) => void;
  disabled?: boolean;
  hint?: string;
}

export const StrategyChips: React.FC<StrategyChipsProps> = ({ label, value, onChange, disabled, hint }) => {
  const toggle = (s: PickerStrategy) => {
    if (value.includes(s)) {
      const next = value.filter((v) => v !== s);
      onChange(next.length > 0 ? next : ['buy_pullback']);
    } else {
      onChange([...value, s]);
    }
  };
  return (
    <div className="flex items-center gap-3">
      <label className="text-xs font-medium text-muted shrink-0">{label}</label>
      <div className="flex flex-wrap gap-2">
        {STRATEGY_OPTIONS.map((o) => {
          const selected = value.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => toggle(o.value)}
              disabled={disabled}
              className={`px-3.5 py-1.5 rounded-full text-xs font-medium transition-all
                ${selected
                  ? 'bg-cyan text-white shadow-glow-cyan'
                  : 'bg-elevated text-secondary border border-border hover:bg-surface-hover hover:border-cyan/20'}
                disabled:opacity-60 disabled:cursor-not-allowed`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
      {hint && <span className="ml-auto text-xs text-muted">{hint}</span>}
    </div>
  );
};

export default StrategyChips;
