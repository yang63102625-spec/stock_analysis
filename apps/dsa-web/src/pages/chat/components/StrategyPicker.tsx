import { useState } from 'react';
import type React from 'react';
import type { StrategyInfo } from '../../../api/agent';

export interface StrategyPickerProps {
  strategies: StrategyInfo[];
  selected: string;
  onSelect: (id: string) => void;
}

export const StrategyPicker: React.FC<StrategyPickerProps> = ({ strategies, selected, onSelect }) => {
  const [hovered, setHovered] = useState<string | null>(null);

  if (strategies.length === 0) return null;

  return (
    <div className="mb-3 flex flex-wrap gap-x-5 gap-y-2 items-start">
      <span className="text-xs text-muted font-medium uppercase tracking-wider flex-shrink-0 mt-1">
        策略
      </span>
      <label className="flex items-center gap-1.5 text-sm cursor-pointer group mt-0.5">
        <input
          type="radio" name="strategy" value=""
          checked={selected === ''}
          onChange={() => onSelect('')}
          className="w-3.5 h-3.5 accent-cyan"
        />
        <span className={`transition-colors text-sm ${selected === '' ? 'text-primary font-medium' : 'text-secondary group-hover:text-primary'}`}>
          通用分析
        </span>
      </label>
      {strategies.map((s) => (
        <label
          key={s.id}
          className="flex items-center gap-1.5 cursor-pointer group relative mt-0.5"
          onMouseEnter={() => setHovered(s.id)}
          onMouseLeave={() => setHovered(null)}
        >
          <input
            type="radio" name="strategy" value={s.id}
            checked={selected === s.id}
            onChange={() => onSelect(s.id)}
            className="w-3.5 h-3.5 accent-cyan"
          />
          <span className={`transition-colors text-sm ${selected === s.id ? 'text-primary font-medium' : 'text-secondary group-hover:text-primary'}`}>
            {s.name}
          </span>
          {hovered === s.id && s.description && (
            <div className="absolute left-0 bottom-full mb-2 z-50 w-64 p-2.5 rounded-lg bg-elevated border border-border shadow-xl text-xs text-secondary leading-relaxed pointer-events-none animate-fade-in">
              <p className="font-medium text-primary mb-1">{s.name}</p>
              <p>{s.description}</p>
            </div>
          )}
        </label>
      ))}
    </div>
  );
};

export default StrategyPicker;
