import { useEffect, useState } from 'react';
import { agentApi, type StrategyInfo } from '../../../api/agent';

export interface UseChatStrategies {
  strategies: StrategyInfo[];
  selectedStrategy: string;
  setSelectedStrategy: (v: string) => void;
}

export function useChatStrategies(): UseChatStrategies {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>('');

  useEffect(() => {
    agentApi.getStrategies().then((res) => {
      // Sort: bull_trend first
      const sorted = [...res.strategies].sort((a, b) => {
        if (a.id === 'bull_trend') return -1;
        if (b.id === 'bull_trend') return 1;
        return 0;
      });
      setStrategies(sorted);
      setSelectedStrategy('');
    }).catch(() => {});
  }, []);

  return { strategies, selectedStrategy, setSelectedStrategy };
}
