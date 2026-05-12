import type React from 'react';
import { QUICK_QUESTIONS, type QuickQuestion } from '../constants';

export interface EmptyChatProps {
  onQuickQuestion: (q: QuickQuestion) => void;
}

export const EmptyChat: React.FC<EmptyChatProps> = ({ onQuickQuestion }) => (
  <div className="h-full flex flex-col items-center justify-center text-center py-12">
    <div className="w-20 h-20 mb-6 rounded-2xl bg-gradient-to-br from-purple/10 to-cyan/10 flex items-center justify-center shadow-sm">
      <svg className="w-10 h-10 text-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    </div>
    <h3 className="text-lg font-semibold text-primary mb-2">开始问股</h3>
    <p className="text-sm text-secondary max-w-md mb-8 leading-relaxed">
      输入「分析 600519」或「茅台现在能买吗」，AI 将调用实时数据工具为您生成决策报告。
    </p>
    <div className="flex flex-wrap gap-3 justify-center max-w-xl">
      {QUICK_QUESTIONS.map((q, i) => (
        <button
          key={i}
          onClick={() => onQuickQuestion(q)}
          className="px-4 py-2 rounded-xl bg-card border border-border text-sm text-secondary
                     hover:text-primary hover:border-cyan/30 hover:bg-cyan/5 transition-all
                     shadow-sm hover:shadow-md"
        >
          {q.label}
        </button>
      ))}
    </div>
  </div>
);

export default EmptyChat;
