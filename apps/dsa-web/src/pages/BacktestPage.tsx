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

        {/* Hero — aligned with HomePage/SettingsPage (w-14 / text-2xl) */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl
                          bg-gradient-to-br from-cyan/15 to-blue-500/10 mb-3 shadow-sm">
            <svg className="w-7 h-7 text-cyan" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round"
                    d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/>
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-primary mb-1.5 tracking-tight">回测</h1>
          <p className="text-sm text-secondary max-w-2xl mx-auto leading-relaxed">
            {activeTab === 'analysis'
              ? '验证历史 AI 分析的准确性：对比预测方向与实际走势，评估止损止盈触发情况'
              : '验证量化选股策略：按历史日期运行筛选器，统计持仓收益与超额收益'}
          </p>
        </div>

        {/* Tabs */}
        <div className="flex justify-center mb-6">
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
