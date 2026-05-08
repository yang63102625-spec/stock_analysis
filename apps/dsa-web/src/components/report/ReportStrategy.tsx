import type React from 'react';
import type { ReportStrategy as ReportStrategyType } from '../../types/analysis';
import { Card } from '../common';

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
}

interface StrategyItemProps {
  label: string;
  value?: string;
  color: string;
}

const StrategyItem: React.FC<StrategyItemProps> = ({
  label,
  value,
  color,
}) => (
  <div className="relative overflow-hidden rounded-lg bg-elevated border border-border p-3 hover:border-border-accent transition-colors">
    <div className="flex flex-col">
      <span className="text-xs text-muted mb-0.5">{label}</span>
      <span
        className="text-lg font-bold font-mono"
        style={{ color: value ? color : 'var(--text-muted)' }}
      >
        {value || '—'}
      </span>
    </div>
    {/* 底部指示条 */}
    <div
      className="absolute bottom-0 left-0 right-0 h-0.5"
      style={{ background: `linear-gradient(90deg, ${color}00, ${color}, ${color}00)` }}
    />
  </div>
);

/**
 * 策略点位区组件 - 终端风格
 */
export const ReportStrategy: React.FC<ReportStrategyProps> = ({ strategy }) => {
  if (!strategy) {
    return null;
  }

  const strategyItems = [
    {
      label: '理想买入',
      value: strategy.idealBuy,
      color: 'var(--color-success)',
    },
    {
      label: '二次买入',
      value: strategy.secondaryBuy,
      color: 'var(--color-cyan)',
    },
    {
      label: '止损价位',
      value: strategy.stopLoss,
      color: 'var(--color-danger)',
    },
    {
      label: '止盈目标',
      value: strategy.takeProfit,
      color: 'var(--color-warning)',
    },
  ];

  return (
    <Card variant="bordered" padding="md">
      <div className="mb-3 flex items-baseline gap-2">
        <span className="label-uppercase">STRATEGY POINTS</span>
        <h3 className="text-base font-semibold text-primary">狙击点位</h3>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {strategyItems.map((item) => (
          <StrategyItem key={item.label} {...item} />
        ))}
      </div>

      {(strategy.positionPct != null || strategy.riskReward != null || strategy.takeProfit2Rule) && (
        <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 text-xs">
          {strategy.positionPct != null && (
            <div className="rounded border border-border bg-elevated p-2">
              <div className="text-muted">建议仓位</div>
              <div className="font-mono font-semibold text-primary">
                {(strategy.positionPct * 100).toFixed(0)}%
              </div>
            </div>
          )}
          {strategy.riskReward != null && (
            <div className="rounded border border-border bg-elevated p-2">
              <div className="text-muted">盈亏比 R/R</div>
              <div className="font-mono font-semibold text-primary">
                {strategy.riskReward.toFixed(2)}
              </div>
            </div>
          )}
          {strategy.takeProfit2Rule && (
            <div className="col-span-2 md:col-span-1 rounded border border-border bg-elevated p-2">
              <div className="text-muted">后续止盈</div>
              <div className="text-primary leading-snug">{strategy.takeProfit2Rule}</div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};
