import type { ProgressStep } from '../../stores/agentChatStore';

export function getCurrentStage(steps: ProgressStep[]): string {
  if (steps.length === 0) return '正在连接...';
  const last = steps[steps.length - 1];
  if (last.type === 'thinking') return last.message || 'AI 正在思考...';
  if (last.type === 'tool_start') return `${last.display_name || last.tool}...`;
  if (last.type === 'tool_done') return `${last.display_name || last.tool} 完成`;
  if (last.type === 'generating') return last.message || '正在生成最终分析...';
  return '处理中...';
}
