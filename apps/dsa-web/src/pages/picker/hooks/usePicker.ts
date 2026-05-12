import { useState, useCallback } from 'react';
import {
  fetchRecommendations,
  type PickerResponse,
  type PickerStrategy,
} from '../../../api/picker';

export interface UsePicker {
  loading: boolean;
  result: PickerResponse | null;
  error: string;
  pickerStrategies: PickerStrategy[];
  setPickerStrategies: (v: PickerStrategy[]) => void;
  handleRun: (onAfterRun?: () => void) => Promise<void>;
}

export function usePicker(): UsePicker {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PickerResponse | null>(null);
  const [error, setError] = useState('');
  const [pickerStrategies, setPickerStrategies] = useState<PickerStrategy[]>(['buy_pullback']);

  const handleRun = useCallback(async (onAfterRun?: () => void) => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const strategies: PickerStrategy[] = pickerStrategies.length > 0 ? pickerStrategies : ['buy_pullback'];
      const data = await fetchRecommendations({ picker_strategies: strategies });
      if (data.success) {
        setResult(data);
        onAfterRun?.();
      } else {
        setError(data.error || 'AI 选股失败');
      }
    } catch (e: unknown) {
      const err = e as { response?: { status?: number }; message?: string };
      if (err?.response?.status === 504) {
        setError('连接上游服务超时：服务端访问外部依赖时超时，请稍后重试，或检查当前网络与代理设置。');
      } else {
        setError(err.message || '网络错误');
      }
    } finally {
      setLoading(false);
    }
  }, [pickerStrategies]);

  return {
    loading, result, error,
    pickerStrategies, setPickerStrategies,
    handleRun,
  };
}
