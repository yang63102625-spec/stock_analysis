import { useEffect, useRef, type MutableRefObject } from 'react';
import { useSearchParams } from 'react-router-dom';
import { historyApi } from '../../../api/history';
import type { FollowUpContext } from '../constants';

/**
 * Reads ?stock=&name=&recordId= from the URL once on mount.
 * If present:
 *   - sets a pre-filled input via the supplied setter
 *   - resolves the report detail and stores it into the supplied followUpContextRef
 *   - clears the query string
 */
export function useFollowUpFromQuery(
  setInput: (v: string) => void,
  followUpContextRef: MutableRefObject<FollowUpContext | null>,
): void {
  const [searchParams, setSearchParams] = useSearchParams();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    const stock = searchParams.get('stock');
    const name = searchParams.get('name');
    const recordId = searchParams.get('recordId');
    if (!stock) return;

    handled.current = true;
    const displayName = name ? `${name}(${stock})` : stock;
    setInput(`请深入分析 ${displayName}`);

    if (recordId) {
      historyApi.getDetail(Number(recordId)).then((report) => {
        const ctx: FollowUpContext = { stock_code: stock, stock_name: name };
        if (report.summary) ctx.previous_analysis_summary = report.summary;
        if (report.strategy) ctx.previous_strategy = report.strategy;
        if (report.meta) {
          ctx.previous_price = report.meta.currentPrice;
          ctx.previous_change_pct = report.meta.changePct;
        }
        followUpContextRef.current = ctx;
      }).catch(() => {});
    }
    setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams, setInput, followUpContextRef]);
}
