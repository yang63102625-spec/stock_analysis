import type React from 'react';
import { STRATEGY_LABELS, type PickerResponse } from '../../../api/picker';
import { ScreenFunnel } from './ScreenFunnel';
import { PickCard } from './PickCard';
import { ScreenedPoolSection } from './ScreenedPoolSection';

const SectorPill: React.FC<{ name: string }> = ({ name }) => (
  <span className="inline-flex items-center gap-1.5 text-sm font-medium
                   bg-cyan/8 text-cyan border border-cyan/15 px-4 py-1.5 rounded-full">
    {name}
  </span>
);

const MarketSummaryCard: React.FC<{ result: PickerResponse }> = ({ result }) => {
  const isStale = result.indices_stale || result.market_summary?.includes('定性判断');
  return (
    <div className="bg-card border border-border rounded-2xl p-8">
      {isStale && (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 flex items-center gap-2">
          <svg className="w-4 h-4 text-amber-500 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          </svg>
          <span className="text-sm text-amber-700">指数实时数据暂不可用，市场判断仅供参考</span>
        </div>
      )}
      <div className="flex items-start justify-between gap-6">
        <div>
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
              <svg className="w-4 h-4 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
              </svg>
            </div>
            <h2 className="text-sm font-semibold text-primary">今日市场</h2>
          </div>
          <p className="text-base text-secondary leading-relaxed">{result.market_summary}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {(result.picker_strategies && result.picker_strategies.length > 0) && (
            <span className="text-xs font-medium text-muted border border-border px-2 py-1 rounded-lg">
              {result.picker_strategies.map((s) => STRATEGY_LABELS[s] ?? s).join('、')}
            </span>
          )}
          <span className="text-sm text-muted whitespace-nowrap bg-elevated px-3 py-1 rounded-lg">
            {result.generated_at}
          </span>
        </div>
      </div>
    </div>
  );
};

export const ResultView: React.FC<{ result: PickerResponse; onBack?: () => void }> = ({ result, onBack }) => {
  const picks = result.picks ?? [];
  const highPicks = picks.filter(p => p.attention === 'high');
  const otherPicks = picks.filter(p => p.attention !== 'high');
  const hasStrategy = result.picker_strategies && result.picker_strategies.length > 0;
  const strategyLabel = hasStrategy
    ? result.picker_strategies!.map((s) => STRATEGY_LABELS[s] ?? s).join('、')
    : STRATEGY_LABELS['buy_pullback'] ?? '买回踩';

  return (
    <div className="space-y-8">
      {onBack && (
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-muted hover:text-primary transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/>
          </svg>
          返回列表
        </button>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted">选股策略：</span>
        <span className="font-medium text-primary">{strategyLabel}</span>
        <span className="text-muted">·</span>
        <span className="text-muted">{result.generated_at}</span>
      </div>

      {result.screen_stats && <ScreenFunnel stats={result.screen_stats} />}

      {result.market_summary && <MarketSummaryCard result={result} />}

      {(result.sectors_to_watch?.length ?? 0) > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-primary mb-4 flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-purple/10 flex items-center justify-center">
              <svg className="w-4 h-4 text-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/>
              </svg>
            </div>
            关注板块
          </h2>
          <div className="flex flex-wrap gap-2.5">
            {result.sectors_to_watch!.map((s) => <SectorPill key={s} name={s} />)}
          </div>
        </div>
      )}

      {highPicks.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-primary mb-4 flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
              <svg className="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/>
              </svg>
            </div>
            重点推荐
            <span className="text-muted font-normal">({highPicks.length})</span>
          </h2>
          <div className="grid gap-4">
            {highPicks.map((p, i) => <PickCard key={p.code} pick={p} index={i} />)}
          </div>
        </div>
      )}

      {otherPicks.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-primary mb-4 flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
              <svg className="w-4 h-4 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
              </svg>
            </div>
            {highPicks.length > 0 ? '其他关注' : '推荐标的'}
            <span className="text-muted font-normal">({otherPicks.length})</span>
          </h2>
          <div className="grid gap-4">
            {otherPicks.map((p, i) => <PickCard key={p.code} pick={p} index={highPicks.length + i} />)}
          </div>
        </div>
      )}

      {(result.screened_pool?.length ?? 0) > 0 && (
        <ScreenedPoolSection
          screenedPool={result.screened_pool}
          screenedPoolByStrategy={result.screened_pool_by_strategy}
        />
      )}

      {result.risk_warning && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50/60 p-6 flex items-start gap-4">
          <div className="w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 text-amber-600" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-amber-800 mb-1">风险提示</p>
            <p className="text-sm text-amber-700 leading-relaxed">{result.risk_warning}</p>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between text-sm text-muted py-4 border-t border-border">
        <span>共 {picks.length} 只推荐 · 耗时 {result.elapsed_seconds}s</span>
        <span>以上内容由 AI 生成，仅供参考，不构成投资建议</span>
      </div>
    </div>
  );
};

export default ResultView;
