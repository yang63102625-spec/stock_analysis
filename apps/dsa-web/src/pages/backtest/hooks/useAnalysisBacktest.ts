import { useState, useEffect, useCallback } from 'react';
import { backtestApi } from '../../../api/backtest';
import type { ParsedApiError } from '../../../api/error';
import { getParsedApiError } from '../../../api/error';
import type {
  BacktestResultItem,
  BacktestRunResponse,
  PerformanceMetrics,
} from '../../../types/backtest';

const PAGE_SIZE = 20;

export interface UseAnalysisBacktest {
  // form
  codeFilter: string;
  setCodeFilter: (v: string) => void;
  evalDays: string;
  setEvalDays: (v: string) => void;
  forceRerun: boolean;
  setForceRerun: (v: boolean) => void;
  // run
  isRunning: boolean;
  runResult: BacktestRunResponse | null;
  runError: ParsedApiError | null;
  handleRun: () => Promise<void>;
  // results
  results: BacktestResultItem[];
  totalResults: number;
  currentPage: number;
  totalPages: number;
  pageSize: number;
  isLoadingResults: boolean;
  pageError: ParsedApiError | null;
  handleFilter: () => void;
  handlePageChange: (page: number) => void;
  // performance
  overallPerf: PerformanceMetrics | null;
  stockPerf: PerformanceMetrics | null;
  isLoadingPerf: boolean;
}

export function useAnalysisBacktest(): UseAnalysisBacktest {
  const [codeFilter, setCodeFilter] = useState('');
  const [evalDays, setEvalDays] = useState('');
  const [forceRerun, setForceRerun] = useState(false);

  const [isRunning, setIsRunning] = useState(false);
  const [runResult, setRunResult] = useState<BacktestRunResponse | null>(null);
  const [runError, setRunError] = useState<ParsedApiError | null>(null);
  const [pageError, setPageError] = useState<ParsedApiError | null>(null);

  const [results, setResults] = useState<BacktestResultItem[]>([]);
  const [totalResults, setTotalResults] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoadingResults, setIsLoadingResults] = useState(false);

  const [overallPerf, setOverallPerf] = useState<PerformanceMetrics | null>(null);
  const [stockPerf, setStockPerf] = useState<PerformanceMetrics | null>(null);
  const [isLoadingPerf, setIsLoadingPerf] = useState(false);

  const fetchResults = useCallback(async (page = 1, code?: string, windowDays?: number) => {
    setIsLoadingResults(true);
    try {
      const response = await backtestApi.getResults({ code: code || undefined, evalWindowDays: windowDays, page, limit: PAGE_SIZE });
      setResults(response.items);
      setTotalResults(response.total);
      setCurrentPage(response.page);
      setPageError(null);
    } catch (err) {
      setPageError(getParsedApiError(err));
    } finally {
      setIsLoadingResults(false);
    }
  }, []);

  const fetchPerformance = useCallback(async (code?: string, windowDays?: number) => {
    setIsLoadingPerf(true);
    try {
      const overall = await backtestApi.getOverallPerformance(windowDays);
      setOverallPerf(overall);
      if (code) {
        const stock = await backtestApi.getStockPerformance(code, windowDays);
        setStockPerf(stock);
      } else {
        setStockPerf(null);
      }
      setPageError(null);
    } catch (err) {
      setPageError(getParsedApiError(err));
    } finally {
      setIsLoadingPerf(false);
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      try {
        const overall = await backtestApi.getOverallPerformance();
        setOverallPerf(overall);
        const windowDays = overall?.evalWindowDays;
        if (windowDays && !evalDays) setEvalDays(String(windowDays));
        fetchResults(1, undefined, windowDays);
      } catch {
        fetchResults(1);
      }
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRun = useCallback(async () => {
    setIsRunning(true);
    setRunResult(null);
    setRunError(null);
    try {
      const code = codeFilter.trim() || undefined;
      const evalWindowDays = evalDays ? parseInt(evalDays, 10) : undefined;
      const response = await backtestApi.run({
        code,
        force: forceRerun || undefined,
        minAgeDays: forceRerun ? 0 : undefined,
        evalWindowDays,
      });
      setRunResult(response);
      fetchResults(1, code, evalWindowDays);
      fetchPerformance(code, evalWindowDays);
    } catch (err) {
      setRunError(getParsedApiError(err));
    } finally {
      setIsRunning(false);
    }
  }, [codeFilter, evalDays, forceRerun, fetchResults, fetchPerformance]);

  const handleFilter = useCallback(() => {
    const code = codeFilter.trim() || undefined;
    const windowDays = evalDays ? parseInt(evalDays, 10) : undefined;
    setCurrentPage(1);
    fetchResults(1, code, windowDays);
    fetchPerformance(code, windowDays);
  }, [codeFilter, evalDays, fetchResults, fetchPerformance]);

  const handlePageChange = useCallback((page: number) => {
    const windowDays = evalDays ? parseInt(evalDays, 10) : undefined;
    fetchResults(page, codeFilter.trim() || undefined, windowDays);
  }, [codeFilter, evalDays, fetchResults]);

  const totalPages = Math.ceil(totalResults / PAGE_SIZE);

  return {
    codeFilter, setCodeFilter,
    evalDays, setEvalDays,
    forceRerun, setForceRerun,
    isRunning, runResult, runError, handleRun,
    results, totalResults, currentPage, totalPages, pageSize: PAGE_SIZE,
    isLoadingResults, pageError, handleFilter, handlePageChange,
    overallPerf, stockPerf, isLoadingPerf,
  };
}
