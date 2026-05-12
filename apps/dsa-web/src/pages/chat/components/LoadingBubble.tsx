import type React from 'react';
import type { ProgressStep } from '../../../stores/agentChatStore';
import { getCurrentStage } from '../utils';

export const LoadingBubble: React.FC<{ steps: ProgressStep[] }> = ({ steps }) => (
  <div className="flex gap-3 animate-fade-in">
    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple/80 to-indigo-500 text-white flex items-center justify-center flex-shrink-0 shadow-sm">
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    </div>
    <div className="bg-card border border-border/80 rounded-2xl rounded-tl-md px-3 py-2 min-w-[150px] max-w-[80%] shadow-sm">
      <div className="flex items-center gap-2.5 text-sm text-secondary">
        <div className="relative w-4 h-4 flex-shrink-0">
          <div className="absolute inset-0 rounded-full border-2 border-cyan/20" />
          <div className="absolute inset-0 rounded-full border-2 border-cyan border-t-transparent animate-spin" />
        </div>
        <span className="text-secondary">{getCurrentStage(steps)}</span>
      </div>
    </div>
  </div>
);

export default LoadingBubble;
