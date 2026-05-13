import type React from 'react';
import { useState } from 'react';
import AnalysisTab from './backtest/AnalysisTab';
import PickerTab from './backtest/PickerTab';

type BacktestTab = 'analysis' | 'picker';

const BacktestPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<BacktestTab>('analysis');

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-6">

        {/* Header: title + tabs */}
        <div className="mb-6 flex-shrink-0 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan/15 to-blue-500/10 flex items-center justify-center shadow-sm">
              <svg className="w-4 h-4 text-cyan" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                      d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/>
              </svg>
            </div>
            <h1 className="text-lg font-semibold text-primary tracking-tight">回测</h1>
          </div>
          <div className="inline-flex p-1 rounded-xl bg-elevated border border-border">
            <button
              type="button"
              onClick={() => setActiveTab('analysis')}
              className={`px-5 py-2 rounded-lg text-sm font-medium transition-all
                ${activeTab === 'analysis'
                  ? 'bg-cyan text-white shadow-sm'
                  : 'text-secondary hover:text-primary hover:bg-white/60'}`}
            >
              分析回测
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('picker')}
              className={`px-5 py-2 rounded-lg text-sm font-medium transition-all
                ${activeTab === 'picker'
                  ? 'bg-cyan text-white shadow-sm'
                  : 'text-secondary hover:text-primary hover:bg-white/60'}`}
            >
              选股回测
            </button>
          </div>
        </div>

        {/* Content */}
        {activeTab === 'analysis' && <AnalysisTab />}
        {activeTab === 'picker' && <PickerTab active={activeTab === 'picker'} />}

      </div>
    </div>
  );
};

export default BacktestPage;
