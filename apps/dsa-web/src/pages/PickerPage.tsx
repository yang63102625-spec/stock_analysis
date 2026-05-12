import type React from 'react';
import { useNavigate } from 'react-router-dom';
import { Spinner } from '../components/common';
import { usePicker } from './picker/hooks/usePicker';
import { usePickerHistory } from './picker/hooks/usePickerHistory';
import { ResultView } from './picker/components/ResultView';
import { PickerEmptyState } from './picker/components/PickerEmptyState';
import { STRATEGY_OPTIONS } from './picker/constants';

const PickerPage: React.FC = () => {
  const navigate = useNavigate();
  const p = usePicker();
  const h = usePickerHistory();

  const onRun = () => p.handleRun(() => { h.reload(); });
  const onSelectHistory = (id: number) => navigate(`/picker/history/${id}`);

  const showingResult = p.result && !p.loading;
  const showEmptyState = !p.loading && !p.result && !p.error;

  const toggleStrategy = (s: typeof STRATEGY_OPTIONS[number]['value']) => {
    if (p.pickerStrategies.includes(s)) {
      const remaining = p.pickerStrategies.filter((x) => x !== s);
      p.setPickerStrategies(remaining.length > 0 ? remaining : ['buy_pullback']);
    } else {
      p.setPickerStrategies([...p.pickerStrategies, s]);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-6">

        {/* Hero — aligned with HomePage/SettingsPage (w-14 / text-2xl) */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl
                          bg-gradient-to-br from-cyan/15 to-blue-500/10 mb-3 shadow-sm">
            <svg className="w-7 h-7 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-primary mb-1.5 tracking-tight">AI 智能选股</h1>
          <p className="text-sm text-secondary max-w-2xl mx-auto leading-relaxed">
            从全市场 5000+ 只 A 股中，经过多层量化筛选缩小范围，再结合板块轮动与新闻热点，
            由 AI 从候选池中精选最值得关注的标的
          </p>
        </div>

        {/* Strategy selector + Action button */}
        <div className="bg-card border border-border rounded-2xl p-6 mb-8 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:flex-wrap items-center justify-center gap-4">
            <span className="text-sm font-semibold text-primary shrink-0">选股策略</span>
            <div className="flex flex-wrap justify-center gap-2">
              {STRATEGY_OPTIONS.map((o) => {
                const selected = p.pickerStrategies.includes(o.value);
                return (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => toggleStrategy(o.value)}
                    disabled={p.loading}
                    className={`px-4 py-2 rounded-xl text-sm font-medium transition-all
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
            <button
              onClick={onRun}
              disabled={p.loading}
              className="shrink-0 group flex items-center gap-2 h-[42px] px-6 rounded-lg
                         bg-gradient-to-r from-cyan to-cyan-dim text-white font-semibold text-[13px]
                         hover:shadow-lg transition-all whitespace-nowrap
                         disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {p.loading ? (
                <>
                  <Spinner size="sm" className="border-white/30 border-t-white" />
                  <span>正在分析市场...</span>
                </>
              ) : (
                <>
                  <svg className="w-4 h-4 transition-transform group-hover:rotate-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z"/>
                  </svg>
                  <span>开始选股</span>
                </>
              )}
            </button>
          </div>
          <p className="text-xs text-muted text-center mt-4">
            买回踩 · 突破 · 底部反转 · 尾盘买入 — 多策略并行，按需组合
          </p>
        </div>

        {/* Loading */}
        {p.loading && (
          <div className="flex flex-col items-center py-20">
            <div className="relative">
              <div className="w-24 h-24 rounded-full border-2 border-cyan/10 flex items-center justify-center">
                <Spinner size="lg" />
              </div>
              <div className="absolute -inset-3 rounded-full border border-cyan/5 animate-ping" style={{ animationDuration: '2s' }} />
            </div>
            <p className="mt-8 text-base text-primary font-semibold">两阶段分析进行中</p>
            <div className="mt-4 flex gap-8 text-sm text-muted">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-cyan animate-pulse" />
                <span>量化筛选</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-purple/50" />
                <span>AI 精选</span>
              </div>
            </div>
            <p className="mt-6 text-xs text-muted">全市场扫描 + 多层过滤 + 新闻检索 + AI 综合分析，预计 30-90 秒</p>
          </div>
        )}

        {/* Error */}
        {p.error && !p.loading && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-6 mb-8 text-center">
            <p className="text-base text-red-700 font-medium">{p.error}</p>
            <button onClick={onRun} className="mt-3 text-sm text-red-600 underline hover:no-underline font-medium">
              重试
            </button>
          </div>
        )}

        {/* Results */}
        {showingResult && <ResultView result={p.result!} />}

        {/* Empty state */}
        {showEmptyState && (
          <PickerEmptyState
            history={h.history}
            historyTotal={h.historyTotal}
            historyLoading={h.historyLoading}
            historyVisibleCount={h.historyVisibleCount}
            onShowMore={() => h.setHistoryVisibleCount((c) => c + 10)}
            onSelect={onSelectHistory}
          />
        )}

      </div>
    </div>
  );
};

export default PickerPage;
