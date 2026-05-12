import { useCallback, useEffect, useState } from 'react';
import { fetchPickerHistory, type PickerHistoryItem } from '../../../api/picker';

export interface UsePickerHistory {
  history: PickerHistoryItem[];
  historyTotal: number;
  historyLoading: boolean;
  historyVisibleCount: number;
  setHistoryVisibleCount: (fn: (c: number) => number) => void;
  reload: () => Promise<void>;
}

export function usePickerHistory(): UsePickerHistory {
  const [history, setHistory] = useState<PickerHistoryItem[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyVisibleCount, setHistoryVisibleCountState] = useState(10);

  const reload = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await fetchPickerHistory(20, 0);
      setHistory(data.items);
      setHistoryTotal(data.total);
    } catch {
      // non-critical
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const setHistoryVisibleCount = useCallback((fn: (c: number) => number) => {
    setHistoryVisibleCountState(fn);
  }, []);

  return { history, historyTotal, historyLoading, historyVisibleCount, setHistoryVisibleCount, reload };
}
