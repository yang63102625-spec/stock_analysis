import type React from 'react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { STRATEGY_LABELS, type ScreenedStock } from '../../../api/picker';

const fmt = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? '—' : v.toFixed(digits);

const numOrZero = (v: number | null | undefined): number =>
  v == null || !Number.isFinite(v) ? 0 : v;

export const ScreenedPoolTable: React.FC<{ pool: ScreenedStock[] }> = ({ pool }) => {
  const [expanded, setExpanded] = useState(false);
  const navigate = useNavigate();
  const goToChat = (s: ScreenedStock) => {
    const params = new URLSearchParams({ stock: s.code });
    if (s.name) params.set('name', s.name);
    navigate(`/chat?${params.toString()}`);
  };
  if (!pool.length) return null;

  const shown = expanded ? pool : pool.slice(0, 10);
  const showStrategyCol = pool.some((x) => x.strategies && x.strategies.length > 0);

  return (
    <div className="bg-card border border-border rounded-2xl overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-surface-hover transition-colors"
      >
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-cyan/10 flex items-center justify-center">
            <svg className="w-4 h-4 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16"/>
            </svg>
          </div>
          <h2 className="text-sm font-semibold text-primary">
            量化候选池 <span className="text-muted font-normal">({pool.length} 只)</span>
          </h2>
        </div>
        <svg
          className={`w-5 h-5 text-muted transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
        </svg>
      </button>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-t border-border bg-elevated/50">
              <th className="px-4 py-2.5 text-left text-xs text-muted font-medium">代码</th>
              <th className="px-4 py-2.5 text-left text-xs text-muted font-medium">名称</th>
              <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">现价</th>
              <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">涨跌%</th>
              <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">量比</th>
              <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">换手%</th>
              <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">PE</th>
              <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">市值(亿)</th>
              <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">60日%</th>
              {showStrategyCol && (
                <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">策略</th>
              )}
              <th className="px-4 py-2.5 text-right text-xs text-muted font-medium">评分</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => (
              <tr
                key={s.code}
                onClick={() => goToChat(s)}
                className="border-t border-border/50 hover:bg-surface-hover/50 cursor-pointer"
              >
                <td className="px-4 py-2 font-mono text-muted">{s.code}</td>
                <td className="px-4 py-2 text-primary font-medium">{s.name}</td>
                <td className="px-4 py-2 text-right tabular-nums">{fmt(s.price, 2)}</td>
                <td className={`px-4 py-2 text-right tabular-nums ${numOrZero(s.change_pct) > 0 ? 'text-red-600' : numOrZero(s.change_pct) < 0 ? 'text-emerald-600' : 'text-muted'}`}>
                  {numOrZero(s.change_pct) > 0 ? '+' : ''}{fmt(s.change_pct, 2)}{s.change_pct == null ? '' : '%'}
                </td>
                <td className={`px-4 py-2 text-right tabular-nums ${numOrZero(s.volume_ratio) > 1.5 ? 'text-red-600 font-medium' : ''}`}>
                  {fmt(s.volume_ratio, 1)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{fmt(s.turnover_rate, 1)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{fmt(s.pe, 0)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{fmt(s.market_cap_yi, 0)}</td>
                <td className={`px-4 py-2 text-right tabular-nums ${numOrZero(s.change_pct_60d) > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                  {numOrZero(s.change_pct_60d) > 0 ? '+' : ''}{fmt(s.change_pct_60d, 1)}{s.change_pct_60d == null ? '' : '%'}
                </td>
                {showStrategyCol && (
                  <td className="px-4 py-2 text-right text-xs text-muted">
                    {(s.strategies || []).map((st) => STRATEGY_LABELS[st] ?? st).join(',')}
                  </td>
                )}
                <td className="px-4 py-2 text-right tabular-nums font-semibold text-cyan">{fmt(s.score, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pool.length > 10 && !expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full py-3 text-sm text-cyan hover:text-cyan/80 border-t border-border font-medium"
        >
          展开全部 {pool.length} 只 ↓
        </button>
      )}
    </div>
  );
};

export default ScreenedPoolTable;
