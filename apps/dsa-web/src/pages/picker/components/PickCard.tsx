import type React from 'react';
import { useNavigate } from 'react-router-dom';
import type { StockPick } from '../../../api/picker';
import { ATTENTION_CFG } from '../constants';

export const PickCard: React.FC<{ pick: StockPick; index: number }> = ({ pick, index }) => {
  const cfg = ATTENTION_CFG[pick.attention] || ATTENTION_CFG.medium;
  const navigate = useNavigate();
  const goToChat = () => {
    const params = new URLSearchParams({ stock: pick.code });
    if (pick.name) params.set('name', pick.name);
    navigate(`/chat?${params.toString()}`);
  };
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={goToChat}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goToChat(); } }}
      className="group relative bg-card border border-border rounded-2xl p-6 cursor-pointer
                    hover:border-border-accent hover:shadow-md transition-all">
      <span className={`absolute left-0 top-5 bottom-5 w-1 rounded-r-full ${cfg.dot} opacity-80`} />

      <div className="flex items-start justify-between mb-4 pl-4">
        <div className="flex items-center gap-4">
          <span className="text-3xl font-bold text-cyan/60 tabular-nums leading-none select-none">
            {String(index + 1).padStart(2, '0')}
          </span>
          <div>
            <div className="flex items-center gap-2.5">
              <h3 className="font-bold text-primary text-lg">{pick.name}</h3>
              <span className="text-sm text-muted font-mono">{pick.code}</span>
            </div>
            {pick.sector && (
              <span className="inline-block mt-0.5 text-xs text-cyan bg-cyan/8 px-2 py-0.5 rounded">
                {pick.sector}
              </span>
            )}
          </div>
        </div>
        <span className={`text-xs font-semibold px-3 py-1.5 rounded-full ring-1 ${cfg.badge}`}>
          {cfg.label}
        </span>
      </div>

      <p className="text-sm text-secondary pl-4 mb-4 leading-relaxed">{pick.reason}</p>

      {pick.ideal_buy !== undefined && pick.ideal_buy > 0 && (
        <div className="ml-4 mb-4 grid grid-cols-2 md:grid-cols-5 gap-2 p-3
                        bg-slate-50 border border-slate-200 rounded-lg text-sm">
          <div>
            <div className="text-xs text-muted">理想买入</div>
            <div className="font-semibold text-primary text-heading-sm tabular-nums">{pick.ideal_buy.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">止损</div>
            <div className="font-semibold text-down text-heading-sm tabular-nums">
              {pick.stop_loss?.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted">首止盈</div>
            <div className="font-semibold text-up text-heading-sm tabular-nums">
              {pick.take_profit_1?.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted">盈亏比</div>
            <div className="font-semibold text-cyan tabular-nums">
              {pick.risk_reward?.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted">建议仓位</div>
            <div className="font-semibold text-amber-600 tabular-nums">
              {pick.position_pct ? `${(pick.position_pct * 100).toFixed(1)}%` : '—'}
            </div>
          </div>
          {pick.take_profit_2_rule && (
            <div className="col-span-2 md:col-span-5 text-xs text-secondary mt-1
                            border-t border-slate-200 pt-2">
              <span className="text-muted">后续止盈：</span>{pick.take_profit_2_rule}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-4 pl-4">
        {pick.resonance && (
          <div className="flex items-center gap-2 text-sm bg-purple-50 rounded-lg px-3 py-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-purple-500 shrink-0" />
            <span className="text-purple-700 font-medium">
              {pick.resonance === 'triple' ? '三策略共振 ⭐⭐⭐' : '双策略共振 ⭐⭐'}
            </span>
          </div>
        )}
        {pick.catalyst && (
          <div className="flex items-center gap-2 text-sm bg-emerald-50 rounded-lg px-3 py-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
            <span className="text-emerald-700 font-medium">催化</span>
            <span className="text-emerald-600">{pick.catalyst}</span>
          </div>
        )}
        {pick.risk_note && (
          <div className="flex items-center gap-2 text-sm bg-red-50 rounded-lg px-3 py-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400 shrink-0" />
            <span className="text-red-600 font-medium">风险</span>
            <span className="text-red-500">{pick.risk_note}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default PickCard;
