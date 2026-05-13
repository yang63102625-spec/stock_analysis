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
        <div className="mb-5 flex-shrink-0 flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500/15 to-indigo-500/10 flex items-center justify-center shadow-sm">
            <svg className="w-4 h-4 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </div>
          <h1 className="text-lg font-semibold text-primary tracking-tight">个股分析</h1>
        </div>

        <div className="flex-1 flex gap-6 min-h-0">
          <div className="hidden md:flex w-64 flex-shrink-0 flex-col gap-3 overflow-hidden p-3 glass-card">
            {sidebarContent}
          </div>

          {sidebarOpen && (
            <div className="fixed inset-0 z-40 md:hidden" onClick={() => setSidebarOpen(false)}>
              <div className="absolute inset-0 bg-black/60" />
              <div
                className="relative absolute left-0 top-0 bottom-0 w-72 flex flex-col glass-card overflow-hidden border-r border-border shadow-2xl p-3"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  className="absolute top-3 right-3 p-2 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition z-10"
                  onClick={() => setSidebarOpen(false)}
                  aria-label="Close sidebar"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
                {sidebarContent}
              </div>
            </div>
          )}

          <section className="flex-1 flex flex-col overflow-hidden min-w-0 p-4 glass-card">
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
