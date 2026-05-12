import type React from 'react';
import { ApiErrorAlert, Spinner } from '../../../components/common';
import { ReportSummary } from '../../../components/report';
import type { AnalysisReport } from '../../../types/analysis';
import type { ParsedApiError } from '../../../api/error';

export interface HomeReportPanelProps {
  analysisError: ParsedApiError | null;
  isLoadingReport: boolean;
  selectedReport: AnalysisReport | null;
}

export const HomeReportPanel: React.FC<HomeReportPanelProps> = ({
  analysisError,
  isLoadingReport,
  selectedReport,
}) => (
  <div className="flex-1 overflow-y-auto overflow-x-auto min-h-0">
    {analysisError ? <ApiErrorAlert error={analysisError} className="mb-3" /> : null}
    {isLoadingReport ? (
      <div className="flex flex-col items-center justify-center h-full">
        <Spinner size="xl" />
        <p className="mt-3 text-secondary text-sm">加载报告中...</p>
      </div>
    ) : selectedReport ? (
      <div>
        <ReportSummary data={selectedReport} isHistory />
      </div>
    ) : (
      <div className="flex flex-col items-center justify-center h-full text-center">
        <div className="w-12 h-12 mb-3 rounded-xl bg-elevated flex items-center justify-center">
          <svg className="w-6 h-6 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
            />
          </svg>
        </div>
        <h3 className="text-base font-medium text-primary mb-1.5">开始分析</h3>
        <p className="text-xs text-muted max-w-xs">输入股票代码进行分析，或从左侧选择历史报告查看</p>
      </div>
    )}
  </div>
);

export default HomeReportPanel;
