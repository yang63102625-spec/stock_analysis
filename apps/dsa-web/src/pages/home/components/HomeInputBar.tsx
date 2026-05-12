import type React from 'react';

export interface HomeInputBarProps {
  stockCode: string;
  onStockCodeChange: (v: string) => void;
  inputError?: string;
  duplicateError?: string | null;
  isAnalyzing: boolean;
  onAnalyze: () => void;
  onOpenSidebar: () => void;
  followUpEnabled: boolean;
  onFollowUp: () => void;
}

/**
 * Top input bar: mobile sidebar trigger + stock code input + analyze button +
 * optional follow-up button (visible only when a report is selected).
 */
export const HomeInputBar: React.FC<HomeInputBarProps> = ({
  stockCode,
  onStockCodeChange,
  inputError,
  duplicateError,
  isAnalyzing,
  onAnalyze,
  onOpenSidebar,
  followUpEnabled,
  onFollowUp,
}) => {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && stockCode && !isAnalyzing) {
      onAnalyze();
    }
  };

  return (
    <div className="mb-4 flex-shrink-0">
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenSidebar}
          className="md:hidden p-2 rounded-lg hover:bg-surface-hover transition-colors text-secondary hover:text-primary flex-shrink-0 border border-border"
          title="历史记录"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <div className="flex-1 relative min-w-0">
          <input
            type="text"
            value={stockCode}
            onChange={(e) => onStockCodeChange(e.target.value.toUpperCase())}
            onKeyDown={handleKeyDown}
            placeholder="输入股票代码，如 600519、00700、AAPL"
            disabled={isAnalyzing}
            className={`input-terminal w-full ${inputError ? 'border-danger/50' : ''}`}
          />
          {inputError && (
            <p className="absolute -bottom-5 left-0 text-xs text-danger">{inputError}</p>
          )}
          {duplicateError && (
            <p className="absolute -bottom-5 left-0 text-xs text-warning">{duplicateError}</p>
          )}
        </div>
        <button
          type="button"
          onClick={onAnalyze}
          disabled={!stockCode || isAnalyzing}
          className="h-[42px] px-5 rounded-lg bg-gradient-to-r from-cyan to-cyan-dim text-white font-semibold text-[13px] hover:shadow-lg transition-all whitespace-nowrap flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
        >
          {isAnalyzing ? (
            <>
              <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              分析中
            </>
          ) : (
            '分析'
          )}
        </button>
        {followUpEnabled && (
          <button
            onClick={onFollowUp}
            className="h-[42px] px-5 rounded-lg bg-purple/10 border border-purple/30 text-purple font-semibold text-[13px] hover:bg-purple/20 transition-all whitespace-nowrap flex-shrink-0"
          >
            追问
          </button>
        )}
      </div>
    </div>
  );
};

export default HomeInputBar;
