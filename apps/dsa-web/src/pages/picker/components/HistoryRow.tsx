import type React from 'react';
import { STRATEGY_LABELS, type PickerHistoryItem } from '../../../api/picker';
import { ATTENTION_CFG } from '../constants';

export const HistoryRow: React.FC<{ item: PickerHistoryItem; onSelect: (id: number) => void }> = ({ item, onSelect }) => {
  const ts = item.created_at ? new Date(item.created_at) : null;
  const dateStr = ts ? `${ts.getFullYear()}-${String(ts.getMonth() + 1).padStart(2, '0')}-${String(ts.getDate()).padStart(2, '0')}` : '';
  const timeStr = ts ? `${String(ts.getHours()).padStart(2, '0')}:${String(ts.getMinutes()).padStart(2, '0')}` : '';

  return (
    <button
      onClick={() => onSelect(item.id)}
      className="w-full text-left bg-card border border-border rounded-xl px-5 py-4
                 hover:border-border-accent hover:shadow-sm transition-all group"
    >
      <div className="flex items-center justify-between gap-4 mb-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-lg bg-cyan/10 flex items-center justify-center shrink-0">
            <svg className="w-4 h-4 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold text-primary">{dateStr}</span>
              <span className="text-xs text-muted">{timeStr}</span>
              <span className="text-xs bg-cyan/10 text-cyan px-2 py-0.5 rounded font-medium">
                {item.pick_count} 只推荐
              </span>
              <span className="text-xs text-muted border border-border px-2 py-0.5 rounded">
                {(item.picker_strategies && item.picker_strategies.length > 0
                  ? item.picker_strategies.map((s: string) => STRATEGY_LABELS[s] ?? s).join('、')
                  : STRATEGY_LABELS['buy_pullback'] ?? '买回踩')}
              </span>
            </div>
            <p className="text-sm text-secondary truncate mt-0.5">{item.market_summary || '—'}</p>
          </div>
        </div>
        <svg className="w-5 h-5 text-muted group-hover:text-cyan shrink-0 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
        </svg>
      </div>

      {(item.picks_preview?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-1.5 ml-12">
          {item.picks_preview.map((p) => {
            const cfg = ATTENTION_CFG[p.attention] || ATTENTION_CFG.medium;
            return (
              <span key={p.code} className={`text-xs px-2 py-0.5 rounded-full ring-1 ${cfg.badge}`}>
                {p.name}
              </span>
            );
          })}
          {item.pick_count > 5 && (
            <span className="text-xs text-muted px-2 py-0.5">+{item.pick_count - 5}</span>
          )}
        </div>
      )}
    </button>
  );
};

export default HistoryRow;
