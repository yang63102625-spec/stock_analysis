import { useState, useCallback } from 'react';
import {
  fetchRecommendations,
  fetchPickerDetail,
  type PickerResponse,
  type PickerStrategy,
} from '../../../api/picker';

export interface UsePicker {
  loading: boolean;
  detailLoading: boolean;
  result: PickerResponse | null;
  error: string;
  pickerStrategies: PickerStrategy[];
  setPickerStrategies: (v: PickerStrategy[]) => void;
  viewingHistoryId: number | null;
  handleRun: (onAfterRun?: () => void) => Promise<void>;
  handleViewHistory: (id: number) => Promise<void>;
  handleBackToList: () => void;
}

export function usePicker(): UsePicker {
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [result, setResult] = useState<PickerResponse | null>(null);
  const [error, setError] = useState('');
  const [pickerStrategies, setPickerStrategies] = useState<PickerStrategy[]>(['buy_pullback']);
  const [viewingHistoryId, setViewingHistoryId] = useState<number | null>(null);

  const handleRun = useCallback(async (onAfterRun?: () => void) => {
    setLoading(true);
    setError('');
    setResult(null);
    setViewingHistoryId(null);
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

  const handleViewHistory = useCallback(async (id: number) => {
    setDetailLoading(true);
    setError('');
    setResult(null);
    setViewingHistoryId(id);
    try {
      const data = await fetchPickerDetail(id);
      setResult(data);
    } catch {
      setError('加载历史记录失败');
      setViewingHistoryId(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleBackToList = useCallback(() => {
    setResult(null);
    setViewingHistoryId(null);
    setError('');
  }, []);

  return {
    loading, detailLoading, result, error,
    pickerStrategies, setPickerStrategies,
    viewingHistoryId,
    handleRun, handleViewHistory, handleBackToList,
  };
}
