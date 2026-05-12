import { useCallback, useEffect, useRef, useState } from 'react';
import { historyApi } from '../../../api/history';
import { getParsedApiError } from '../../../api/error';
import type { HistoryItem, AnalysisReport } from '../../../types/analysis';
import { getRecentStartDate, getTodayInShanghai } from '../../../utils/format';
import { useAnalysisStore } from '../../../stores/analysisStore';

const PAGE_SIZE = 20;

export interface UseHistoryList {
  historyItems: HistoryItem[];
  isLoadingHistory: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  selectedReport: AnalysisReport | null;
  isLoadingReport: boolean;
  setSelectedReport: (report: AnalysisReport | null) => void;
  fetchHistory: (autoSelectFirst?: boolean, reset?: boolean, silent?: boolean) => Promise<void>;
  handleLoadMore: () => void;
  handleHistoryClick: (recordId: number) => Promise<void>;
}

/**
 * History list paging + selected report detail loading.
 * Internally tracks request id to discard stale auto-select / click results.
 */
export function useHistoryList(): UseHistoryList {
  const { setError: setStoreError } = useAnalysisStore();

  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);

  const [selectedReport, setSelectedReport] = useState<AnalysisReport | null>(null);
  const [isLoadingReport, setIsLoadingReport] = useState(false);

  const currentPageRef = useRef(currentPage);
  currentPageRef.current = currentPage;
  const historyItemsRef = useRef(historyItems);
  historyItemsRef.current = historyItems;
  const selectedReportRef = useRef(selectedReport);
  selectedReportRef.current = selectedReport;

  const reportRequestIdRef = useRef(0);

  const fetchHistory = useCallback(
    async (autoSelectFirst = false, reset = true, silent = false) => {
      if (!silent) {
        if (reset) {
          setIsLoadingHistory(true);
          setCurrentPage(1);
        } else {
          setIsLoadingMore(true);
        }
      }

      // page is always 1 when reset=true; the ref is only used for load-more
      // (reset=false) to get the next page number.
      const page = reset ? 1 : currentPageRef.current + 1;

      try {
        const response = await historyApi.getList({
          startDate: getRecentStartDate(30),
          endDate: getTodayInShanghai(),
          page,
          limit: PAGE_SIZE,
        });

        if (silent && reset) {
          // Background refresh: merge new items to the top, keep loaded pages.
          setHistoryItems((prev) => {
            const existingIds = new Set(prev.map((item) => item.id));
            const newItems = response.items.filter((item) => !existingIds.has(item.id));
            return newItems.length > 0 ? [...newItems, ...prev] : prev;
          });
        } else if (reset) {
          setHistoryItems(response.items);
          setCurrentPage(1);
        } else {
          setHistoryItems((prev) => [...prev, ...response.items]);
          setCurrentPage(page);
        }

        if (!silent) {
          const totalLoaded = reset
            ? response.items.length
            : historyItemsRef.current.length + response.items.length;
          setHasMore(totalLoaded < response.total);
        }

        if (autoSelectFirst && response.items.length > 0 && !selectedReportRef.current) {
          const firstItem = response.items[0];
          const requestId = ++reportRequestIdRef.current;
          setIsLoadingReport(true);
          try {
            const report = await historyApi.getDetail(firstItem.id);
            if (requestId === reportRequestIdRef.current) {
              setStoreError(null);
              setSelectedReport(report);
            }
          } catch (err) {
            console.error('Failed to fetch first report:', err);
            setStoreError(getParsedApiError(err));
          } finally {
            setIsLoadingReport(false);
          }
        }
      } catch (err) {
        console.error('Failed to fetch history:', err);
        setStoreError(getParsedApiError(err));
      } finally {
        setIsLoadingHistory(false);
        setIsLoadingMore(false);
      }
    },
    [setStoreError],
  );

  const handleLoadMore = useCallback(() => {
    if (!isLoadingMore && hasMore) {
      void fetchHistory(false, false);
    }
  }, [fetchHistory, isLoadingMore, hasMore]);

  const handleHistoryClick = useCallback(
    async (recordId: number) => {
      const requestId = ++reportRequestIdRef.current;
      try {
        const report = await historyApi.getDetail(recordId);
        if (requestId === reportRequestIdRef.current) {
          setStoreError(null);
          setSelectedReport(report);
        }
      } catch (err) {
        console.error('Failed to fetch report:', err);
        setStoreError(getParsedApiError(err));
      }
    },
    [setStoreError],
  );

  // Initial load + auto-select first record.
  useEffect(() => {
    void fetchHistory(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Background polling every 30s to pick up CLI-initiated analyses.
  useEffect(() => {
    const interval = setInterval(() => {
      void fetchHistory(false, true, true);
    }, 30_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh when tab regains visibility.
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        void fetchHistory(false, true, true);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    historyItems,
    isLoadingHistory,
    isLoadingMore,
    hasMore,
    selectedReport,
    isLoadingReport,
    setSelectedReport,
    fetchHistory,
    handleLoadMore,
    handleHistoryClick,
  };
}
