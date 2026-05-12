import type React from 'react';
import { useState } from 'react';
import { STRATEGY_LABELS, type ScreenedStock } from '../../../api/picker';
import { ScreenedPoolTable } from './ScreenedPoolTable';

export const ScreenedPoolSection: React.FC<{
  screenedPool: ScreenedStock[];
  screenedPoolByStrategy?: Record<string, ScreenedStock[]>;
}> = ({ screenedPool, screenedPoolByStrategy }) => {
  const hasByStrategy = screenedPoolByStrategy && Object.keys(screenedPoolByStrategy).length > 0;
  const [viewMode, setViewMode] = useState<'merged' | 'by_strategy'>(hasByStrategy ? 'by_strategy' : 'merged');

  if (!hasByStrategy) {
    return <ScreenedPoolTable pool={screenedPool} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-muted">候选池视图：</span>
        <div className="inline-flex rounded-lg border border-border bg-elevated/50 p-0.5">
          <button
            onClick={() => setViewMode('merged')}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${
              viewMode === 'merged' ? 'bg-cyan text-white' : 'text-muted hover:text-primary'
            }`}
          >
            合并
          </button>
          <button
            onClick={() => setViewMode('by_strategy')}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${
              viewMode === 'by_strategy' ? 'bg-cyan text-white' : 'text-muted hover:text-primary'
            }`}
          >
            按策略对比
          </button>
        </div>
      </div>
      {viewMode === 'merged' ? (
        <ScreenedPoolTable pool={screenedPool} />
      ) : (
        <div className="space-y-6">
          {Object.entries(screenedPoolByStrategy!).map(([strategyId, pool]) => (
            <div key={strategyId}>
              <h3 className="text-sm font-semibold text-primary mb-3 flex items-center gap-2">
                <span className="bg-cyan/10 text-cyan px-2 py-0.5 rounded">
                  {STRATEGY_LABELS[strategyId] ?? strategyId}
                </span>
                <span className="text-muted font-normal">({pool.length} 只)</span>
              </h3>
              <ScreenedPoolTable pool={pool} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ScreenedPoolSection;
