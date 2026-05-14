import type React from 'react';
import type { ReportSummary as ReportSummaryType } from '../../types/analysis';
import { Card, Skeleton, SkeletonScoreBar } from '../common';

interface ReportScoresProps {
  summary?: ReportSummaryType;
}

interface DimItem {
  label: string;
  value?: number;
  cap: number;
}

const SignalBadge: React.FC<{ signal?: string }> = ({ signal }) => {
  if (!signal) return null;
  const map: Record<string, string> = {
    STRONG_BUY: 'bg-success/15 text-success border-success/40',
    BUY: 'bg-success/10 text-success border-success/30',
    HOLD: 'bg-elevated text-secondary border-border',
    AVOID: 'bg-warning/10 text-warning border-warning/30',
    STRONG_AVOID: 'bg-danger/15 text-danger border-danger/40',
  };
  const cls = map[signal] || 'bg-elevated text-secondary border-border';
  return (
    <span className={`px-2 py-0.5 rounded border text-xs font-semibold ${cls}`}>{signal}</span>
  );
};

const RegimeBadge: React.FC<{ env?: string }> = ({ env }) => {
  if (!env) return null;
  const text =
    env === 'bull' ? '牛市' :
    env === 'bear' ? '熊市' :
    env === 'strong_bear' ? '强熊' :
    env === 'sideways' ? '震荡' : env;
  return (
    <span className="px-2 py-0.5 rounded border border-border bg-elevated text-xs text-secondary">
      大盘：{text}
    </span>
  );
};

const DimBar: React.FC<DimItem> = ({ label, value, cap }) => {
  const v = value ?? 0;
  const pct = cap > 0 ? Math.min(100, (v / cap) * 100) : 0;
  return (
    <div>
      <div className="flex justify-between text-xs text-muted mb-0.5">
        <span>{label}</span>
        <span className="font-mono">{v}/{cap}</span>
      </div>
      <div className="h-1.5 rounded bg-elevated overflow-hidden">
        <div className="h-full bg-cyan/60" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
};

/**
 * Skeleton placeholder for ReportScores while loading
 */
export const ReportScoresSkeleton: React.FC = () => (
  <Card variant="bordered" padding="md">
    <div className="mb-3 flex flex-wrap items-baseline gap-2">
      <Skeleton width="w-24" height="h-3" />
      <Skeleton width="w-28" height="h-5" />
      <Skeleton width="w-12" height="h-6" className="ml-auto" />
    </div>
    <div className="flex flex-wrap gap-2 mb-3">
      <Skeleton width="w-20" height="h-5" rounded="rounded" />
      <Skeleton width="w-16" height="h-5" rounded="rounded" />
      <Skeleton width="w-14" height="h-5" rounded="rounded" />
    </div>
    <SkeletonScoreBar />
  </Card>
);

export const ReportScores: React.FC<ReportScoresProps> = ({ summary }) => {
  if (!summary) return null;
  const { signalScore, buySignal, peRatio, marketEnvironment } = summary;
  const hasAny =
    signalScore != null ||
    buySignal ||
    peRatio != null ||
    marketEnvironment ||
    summary.trendScore != null ||
    summary.macdScore != null;
  if (!hasAny) return null;

  const dims: DimItem[] = [
    { label: '趋势', value: summary.trendScore, cap: 30 },
    { label: '乖离', value: summary.biasScore, cap: 15 },
    { label: '量能', value: summary.volumeScore, cap: 18 },
    { label: 'MACD', value: summary.macdScore, cap: 13 },
    { label: '资金流', value: summary.capitalFlowScore, cap: 13 },
    { label: '支撑', value: summary.supportScore, cap: 6 },
    { label: 'RSI', value: summary.rsiScore, cap: 5 },
  ];

  return (
    <Card variant="bordered" padding="md">
      <div className="mb-3 flex flex-wrap items-baseline gap-2">
        <span className="label-uppercase">QUANT SIGNALS</span>
        <h3 className="text-sm font-semibold text-primary">系统量化评分</h3>
        {signalScore != null && (
          <span className="ml-auto font-mono text-xl font-bold text-primary tabular-nums">
            {signalScore}<span className="text-xs text-muted">/100</span>
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        <SignalBadge signal={buySignal} />
        <RegimeBadge env={marketEnvironment} />
        {peRatio != null && (
          <span className="px-2 py-0.5 rounded border border-border bg-elevated text-xs text-secondary">
            PE：<span className="font-mono">{peRatio.toFixed(2)}</span>
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-2">
        {dims.map((d) => <DimBar key={d.label} {...d} />)}
      </div>
    </Card>
  );
};
