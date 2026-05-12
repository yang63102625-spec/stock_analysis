import { useState, useEffect, useCallback } from 'react';
import { pickerBacktestApi } from '../../../api/pickerBacktest';
import type { ParsedApiError } from '../../../api/error';
import { getParsedApiError } from '../../../api/error';
import type {
  PickerBacktestResultItem,
  PickerBacktestSummary,
  PickerBacktestHistoryItem,
  PickerStrategy,
} from '../../../types/pickerBacktest';

interface PickerResultState {
  results: PickerBacktestResultItem[];
  summary: PickerBacktestSummary | null;
}

export interface UsePickerBacktest {
  startDate: string;
  setStartDate: (v: string) => void;
  endDate: string;
  setEndDate: (v: string) => void;
  holdDays: string;
  setHoldDays: (v: string) => void;
  topN: string;
  setTopN: (v: string) => void;
  strategies: PickerStrategy[];
  setStrategies: (v: PickerStrategy[]) => void;

  running: boolean;
  result: PickerResultState | null;
  error: ParsedApiError | null;
  history: PickerBacktestHistoryItem[];

  handleRun: () => Promise<void>;
  handleLoadHistoryDetail: (id: number) => Promise<void>;
  /** Call when tab becomes active to lazy-load last result + history */
  loadOnActivate: () => Promise<void>;
}

export function usePickerBacktest(): UsePickerBacktest {
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 3);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [holdDays, setHoldDays] = useState('10');
  const [topN, setTopN] = useState('5');
  const [strategies, setStrategies] = useState<PickerStrategy[]>(['buy_pullback']);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PickerResultState | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [history, setHistory] = useState<PickerBacktestHistoryItem[]>([]);

  const refreshHistory = useCallback(async () => {
    try {
      const hist = await pickerBacktestApi.getHistory({ limit: 10 });
      setHistory(hist.items);
    } catch {
      // non-critical
    }
  }, []);

  const loadOnActivate = useCallback(async () => {
    try {
      if (result == null) {
        const data = await pickerBacktestApi.getResults();
        if (data.results.length > 0 || data.summary) {
          setResult({ results: data.results, summary: data.summary });
        }
      }
      await refreshHistory();
    } catch {
      // non-critical
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshHistory]);

  // Auto-load history once on mount so it's already warm when tab opens.
  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setResult(null);
    setError(null);
    const hold = parseInt(holdDays, 10) || 10;
    const top = parseInt(topN, 10) || 5;
    try {
      const picks: PickerStrategy[] = strategies.length > 0 ? strategies : ['buy_pullback'];
      const response = await pickerBacktestApi.run({
        startDate, endDate,
        holdDays: hold, topN: top,
        pickerStrategies: picks,
      });
      setResult({ results: response.results, summary: response.summary });
      await refreshHistory();
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setRunning(false);
    }
  }, [startDate, endDate, holdDays, topN, strategies, refreshHistory]);

  const handleLoadHistoryDetail = useCallback(async (id: number) => {
    try {
      const data = await pickerBacktestApi.getHistoryDetail(id);
      setResult({ results: data.results, summary: data.summary });
      setError(null);
    } catch (err) {
      setError(getParsedApiError(err));
    }
  }, []);

  return {
    startDate, setStartDate,
    endDate, setEndDate,
    holdDays, setHoldDays,
    topN, setTopN,
    strategies, setStrategies,
    running, result, error, history,
    handleRun, handleLoadHistoryDetail, loadOnActivate,
  };
}
