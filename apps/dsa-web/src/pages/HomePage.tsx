import type React from 'react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAnalysisStore } from '../stores/analysisStore';
import { HistoryList } from '../components/history';
import { TaskPanel } from '../components/tasks';
import { useHistoryList } from './home/hooks/useHistoryList';
import { useActiveTasks } from './home/hooks/useActiveTasks';
import { useAnalysisInput } from './home/hooks/useAnalysisInput';
import { HomeInputBar } from './home/components/HomeInputBar';
import { HomeReportPanel } from './home/components/HomeReportPanel';

/**
 * Home page - single-page layout: top input + left history sidebar + right report.
 */
const HomePage: React.FC = () => {
  const { error: analysisError } = useAnalysisStore();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const history = useHistoryList();
  const { activeTasks } = useActiveTasks(() => {
    void history.fetchHistory(false, true, true);
  });
  const input = useAnalysisInput();

  const handleFollowUp = () => {
    const report = history.selectedReport;
    if (!report || report.meta.id === undefined) return;
    const code = report.meta.stockCode;
    const name = report.meta.stockName;
    const rid = report.meta.id;
    navigate(`/chat?stock=${encodeURIComponent(code)}&name=${encodeURIComponent(name)}&recordId=${rid}`);
  };

  const sidebarContent = (
    <div className="flex flex-col gap-3 overflow-hidden min-h-0 h-full">
      <TaskPanel tasks={activeTasks} />
      <HistoryList
        items={history.historyItems}
        isLoading={history.isLoadingHistory}
        isLoadingMore={history.isLoadingMore}
        hasMore={history.hasMore}
        selectedId={history.selectedReport?.meta.id}
        onItemClick={(id) => {
          void history.handleHistoryClick(id);
          setSidebarOpen(false);
        }}
        onLoadMore={history.handleLoadMore}
        className="max-h-[62vh] md:max-h-[62vh] flex-1 overflow-hidden"
      />
    </div>
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-6 flex flex-col min-h-screen">
        <div className="text-center mb-6 flex-shrink-0">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-cyan/15 to-blue-500/10 mb-3 shadow-sm">
            <svg className="w-7 h-7 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
              />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-primary mb-1.5 tracking-tight">个股分析</h1>
          <p className="text-sm text-secondary max-w-md mx-auto">
            输入股票代码获取 AI 智能分析报告，支持 A股、港股、美股
          </p>
        </div>

        <div className="flex-1 flex gap-6 min-h-0">
          <div className="hidden md:flex w-64 flex-shrink-0 flex-col gap-3 overflow-hidden">
            {sidebarContent}
          </div>

          {sidebarOpen && (
            <div className="fixed inset-0 z-40 md:hidden" onClick={() => setSidebarOpen(false)}>
              <div className="absolute inset-0 bg-black/60" />
              <div
                className="absolute left-0 top-0 bottom-0 w-72 flex flex-col glass-card overflow-hidden border-r border-border shadow-2xl p-3"
                onClick={(e) => e.stopPropagation()}
              >
                {sidebarContent}
              </div>
            </div>
          )}

          <section className="flex-1 flex flex-col overflow-hidden min-w-0">
            <HomeInputBar
              stockCode={input.stockCode}
              onStockCodeChange={input.setStockCode}
              inputError={input.inputError}
              duplicateError={input.duplicateError}
              isAnalyzing={input.isAnalyzing}
              onAnalyze={() => void input.handleAnalyze()}
              onOpenSidebar={() => setSidebarOpen(true)}
              followUpEnabled={!!history.selectedReport && history.selectedReport.meta.id !== undefined}
              onFollowUp={handleFollowUp}
            />
            <HomeReportPanel
              analysisError={analysisError}
              isLoadingReport={history.isLoadingReport}
              selectedReport={history.selectedReport}
            />
          </section>
        </div>
      </div>
    </div>
  );
};

export default HomePage;
