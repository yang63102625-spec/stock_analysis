import type React from 'react';
import type { ProgressStep } from '../../../stores/agentChatStore';

const ThinkingDetails: React.FC<{ steps: ProgressStep[] }> = ({ steps }) => (
  <div className="mb-3 pl-5 border-l border-border space-y-0.5 animate-fade-in">
    {steps.map((step, idx) => {
      let icon = '⋯';
      let text = '';
      let colorClass = 'text-muted';
      if (step.type === 'thinking') {
        icon = '🤔';
        text = step.message || `第 ${step.step} 步：思考`;
        colorClass = 'text-secondary';
      } else if (step.type === 'tool_start') {
        icon = '⚙️';
        text = `${step.display_name || step.tool}...`;
        colorClass = 'text-secondary';
      } else if (step.type === 'tool_done') {
        icon = step.success ? '✅' : '❌';
        text = `${step.display_name || step.tool} (${step.duration}s)`;
        colorClass = step.success ? 'text-emerald-600' : 'text-red-600';
      } else if (step.type === 'generating') {
        icon = '✍️';
        text = step.message || '生成分析';
        colorClass = 'text-cyan';
      }
      return (
        <div key={idx} className={`flex items-center gap-2 text-xs py-0.5 ${colorClass}`}>
          <span className="w-4 flex-shrink-0 text-center">{icon}</span>
          <span className="leading-relaxed">{text}</span>
        </div>
      );
    })}
  </div>
);

export interface ThinkingBlockProps {
  steps: ProgressStep[];
  expanded: boolean;
  onToggle: () => void;
}

export const ThinkingBlock: React.FC<ThinkingBlockProps> = ({ steps, expanded, onToggle }) => {
  if (!steps || steps.length === 0) return null;
  const toolSteps = steps.filter((s) => s.type === 'tool_done');
  const totalDuration = toolSteps.reduce((sum, s) => sum + (s.duration || 0), 0);
  const summary = `${toolSteps.length} 个工具调用 · ${totalDuration.toFixed(1)}s`;

  return (
    <>
      <button
        onClick={onToggle}
        className="flex items-center gap-2 text-xs text-muted hover:text-secondary transition-colors mb-2 w-full text-left"
      >
        <svg
          className={`w-3 h-3 transition-transform flex-shrink-0 ${expanded ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="flex items-center gap-1.5">
          <span className="opacity-60">思考过程</span>
          <span className="text-muted/50">·</span>
          <span className="opacity-50">{summary}</span>
        </span>
      </button>
      {expanded && <ThinkingDetails steps={steps} />}
    </>
  );
};

export default ThinkingBlock;
