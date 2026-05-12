export interface FollowUpContext {
  stock_code: string;
  stock_name: string | null;
  previous_analysis_summary?: unknown;
  previous_strategy?: unknown;
  previous_price?: number;
  previous_change_pct?: number;
}

export interface QuickQuestion {
  label: string;
  strategy: string;
}

export const QUICK_QUESTIONS: QuickQuestion[] = [
  { label: '用缠论分析茅台', strategy: 'chan_theory' },
  { label: '波浪理论看宁德时代', strategy: 'wave_theory' },
  { label: '分析比亚迪趋势', strategy: 'bull_trend' },
  { label: '箱体震荡策略看中芯国际', strategy: 'box_oscillation' },
  { label: '分析腾讯 hk00700', strategy: 'bull_trend' },
  { label: '用情绪周期分析东方财富', strategy: 'emotion_cycle' },
];
