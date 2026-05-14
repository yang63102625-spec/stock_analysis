import type React from 'react';
import type { ReportMeta, ReportSummary as ReportSummaryType } from '../../types/analysis';
import { ScoreGauge, Card, Skeleton, SkeletonText } from '../common';
import { formatDateTime } from '../../utils/format';

/** Maps operation advice text to a semantic colored badge */
const AdviceBadge: React.FC<{ advice: string }> = ({ advice }) => {
  const lower = advice.toLowerCase();
  let cls = 'bg-elevated text-secondary border border-border'; // default: neutral
  if (/买入|看好|建仓|加仓|追入|看涨/.test(lower)) {
    cls = 'bg-up-subtle text-up border border-transparent';
  } else if (/卖出|清仓|减仓|回避|看跌/.test(lower)) {
    cls = 'bg-down-subtle text-down border border-transparent';
  } else if (/观望|持有|等待/.test(lower)) {
    cls = 'bg-elevated text-secondary border border-border';
  }
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-md text-sm font-semibold ${cls}`}>
      {advice}
    </span>
  );
};

/**
 * Skeleton placeholder for ReportOverview while loading
 */
export const ReportOverviewSkeleton: React.FC = () => (
  <div className="space-y-4">
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-stretch">
      {/* Left: stock info + conclusion skeleton */}
      <div className="lg:col-span-2 space-y-4">
        <div className="p-5 rounded-xl border border-gray-100 space-y-4">
          <div className="flex items-start justify-between mb-4">
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <Skeleton width="w-32" height="h-7" rounded="rounded-md" />
                <Skeleton width="w-16" height="h-6" rounded="rounded-md" />
                <Skeleton width="w-14" height="h-4" rounded="rounded-md" />
              </div>
              <div className="flex items-center gap-2 mt-2">
                <Skeleton width="w-20" height="h-5" rounded="rounded" />
                <Skeleton width="w-36" height="h-4" rounded="rounded" />
              </div>
            </div>
          </div>
          <div className="border-t border-gray-100 pt-4">
            <Skeleton width="w-24" height="h-3" className="mb-2" />
            <SkeletonText lines={3} />
          </div>
        </div>
        {/* Action advice + trend prediction skeleton */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="p-4 rounded-xl border border-gray-100">
            <div className="flex items-start gap-3">
              <Skeleton width="w-8" height="h-8" rounded="rounded-lg" />
              <div className="flex-1 space-y-2">
                <Skeleton width="w-16" height="h-3" />
                <Skeleton width="w-full" height="h-4" />
              </div>
            </div>
          </div>
          <div className="p-4 rounded-xl border border-gray-100">
            <div className="flex items-start gap-3">
              <Skeleton width="w-8" height="h-8" rounded="rounded-lg" />
              <div className="flex-1 space-y-2">
                <Skeleton width="w-16" height="h-3" />
                <Skeleton width="w-full" height="h-4" />
              </div>
            </div>
          </div>
        </div>
      </div>
      {/* Right: gauge skeleton */}
      <div className="flex flex-col self-stretch min-h-full">
        <div className="p-5 rounded-xl border border-gray-100 flex-1 flex flex-col items-center justify-center">
          <Skeleton width="w-20" height="h-4" className="mb-4" />
          <Skeleton width="w-32" height="h-32" rounded="rounded-full" />
        </div>
      </div>
    </div>
  </div>
);

interface ReportOverviewProps {
  meta: ReportMeta;
  summary: ReportSummaryType;
  isHistory?: boolean;
}

/**
 * 报告概览区组件 - 终端风格
 */
export const ReportOverview: React.FC<ReportOverviewProps> = ({
  meta,
  summary
}) => {
  const getPriceChangeColor = (changePct: number | undefined): string => {
    if (changePct === undefined || changePct === null) return 'text-muted';
    if (changePct > 0) return 'text-up';
    if (changePct < 0) return 'text-down';
    return 'text-muted';
  };

  // 格式化涨跌幅
  const formatChangePct = (changePct: number | undefined): string => {
    if (changePct === undefined || changePct === null) return '--';
    const sign = changePct > 0 ? '+' : '';
    return `${sign}${changePct.toFixed(2)}%`;
  };

  return (
    <div className="space-y-4">
      {/* 主信息区 - 两列布局，items-stretch 确保右侧与左侧同高 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-stretch">
        {/* 左侧：股票信息与结论 */}
        <div className="lg:col-span-2 space-y-4">
          {/* 股票头部 */}
          <Card variant="gradient" padding="md">
            <div className="flex items-start justify-between mb-4">
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <h2 className="text-2xl font-bold text-primary">
                    {meta.stockName || meta.stockCode}
                  </h2>
                  {/* 价格和涨跌幅 */}
                  {meta.currentPrice != null && (
                    <div className="flex items-baseline gap-2">
                      <span className={`text-heading-sm tabular-nums font-mono ${getPriceChangeColor(meta.changePct)}`}>
                        {meta.currentPrice.toFixed(2)}
                      </span>
                      <span className={`text-sm font-semibold tabular-nums font-mono ${getPriceChangeColor(meta.changePct)}`}>
                        {meta.changePct !== undefined && meta.changePct !== null
                          ? `${meta.changePct >= 0 ? '↑' : '↓'} ${formatChangePct(meta.changePct)}`
                          : '--'}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="font-mono text-xs text-cyan bg-cyan/10 px-1.5 py-0.5 rounded-md">
                    {meta.stockCode}
                  </span>
                  <span className="text-xs text-muted flex items-center gap-1">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    {formatDateTime(meta.createdAt)}
                  </span>
                </div>
              </div>
            </div>

            {/* 关键结论 */}
            <div className="border-t border-border pt-4">
              <span className="label-uppercase">KEY INSIGHTS</span>
              <p className="text-primary text-sm leading-relaxed mt-1.5 whitespace-pre-wrap text-left">
                {summary.analysisSummary || '暂无分析结论'}
              </p>
            </div>
          </Card>

          {/* 操作建议和趋势预测 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* 操作建议 */}
            <Card variant="bordered" padding="sm" hoverable>
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-success/10 to-success/5 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-xs font-medium text-success mb-0.5">操作建议</h4>
                  <p className="text-primary text-sm font-medium">
                    {summary.operationAdvice ? (
                      <AdviceBadge advice={summary.operationAdvice} />
                    ) : '暂无建议'}
                  </p>
                </div>
              </div>
            </Card>

            {/* 趋势预测 */}
            <Card variant="bordered" padding="sm" hoverable>
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-warning/10 to-warning/5 flex items-center justify-center flex-shrink-0">
                  <svg className="w-4 h-4 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-xs font-medium text-warning mb-0.5">趋势预测</h4>
                  <p className="text-primary text-sm font-medium">
                    {summary.trendPrediction || '暂无预测'}
                  </p>
                </div>
              </div>
            </Card>
          </div>
        </div>

        {/* 右侧：情绪指标 - 填满格子高度，消除与 STRATEGY POINTS 之间的空隙 */}
        <div className="flex flex-col self-stretch min-h-full">
          <Card variant="bordered" padding="md" className="!overflow-visible flex-1 flex flex-col min-h-0">
            <div className="text-center flex-1 flex flex-col justify-center">
              <h3 className="text-sm font-medium text-secondary mb-4">市场情绪</h3>
              <ScoreGauge score={summary.sentimentScore} size="lg" />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
