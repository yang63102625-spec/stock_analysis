import { useCallback, useState } from 'react';
import { analysisApi, DuplicateTaskError } from '../../../api/analysis';
import { getParsedApiError } from '../../../api/error';
import { validateStockCode } from '../../../utils/validation';
import { useAnalysisStore } from '../../../stores/analysisStore';

export interface UseAnalysisInput {
  stockCode: string;
  setStockCode: (v: string) => void;
  inputError: string | undefined;
  duplicateError: string | null;
  isAnalyzing: boolean;
  handleAnalyze: () => Promise<void>;
  clearInputError: () => void;
}

/**
 * Stock-code input form state + async submission to the analysis API.
 */
export function useAnalysisInput(): UseAnalysisInput {
  const { setLoading, setError: setStoreError } = useAnalysisStore();

  const [stockCode, setStockCodeState] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [inputError, setInputError] = useState<string>();
  const [duplicateError, setDuplicateError] = useState<string | null>(null);

  const setStockCode = useCallback((v: string) => {
    setStockCodeState(v);
    setInputError(undefined);
  }, []);

  const clearInputError = useCallback(() => setInputError(undefined), []);

  const handleAnalyze = useCallback(async () => {
    const { valid, message, normalized } = validateStockCode(stockCode);
    if (!valid) {
      setInputError(message);
      return;
    }

    setInputError(undefined);
    setDuplicateError(null);
    setIsAnalyzing(true);
    setLoading(true);
    setStoreError(null);

    try {
      const response = await analysisApi.analyzeAsync({
        stockCode: normalized,
        reportType: 'detailed',
      });
      setStockCodeState('');
      console.log('Task submitted:', response.taskId);
    } catch (err) {
      console.error('Analysis failed:', err);
      if (err instanceof DuplicateTaskError) {
        setDuplicateError(`股票 ${err.stockCode} 正在分析中，请等待完成`);
      } else {
        setStoreError(getParsedApiError(err));
      }
    } finally {
      setIsAnalyzing(false);
      setLoading(false);
    }
  }, [stockCode, setLoading, setStoreError]);

  return {
    stockCode,
    setStockCode,
    inputError,
    duplicateError,
    isAnalyzing,
    handleAnalyze,
    clearInputError,
  };
}
