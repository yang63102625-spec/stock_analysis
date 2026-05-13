import type React from 'react';

interface SkeletonProps {
  className?: string;
  width?: string;
  height?: string;
  rounded?: string;
}

// Base skeleton block
export const Skeleton: React.FC<SkeletonProps> = ({
  className = '',
  width = 'w-full',
  height = 'h-4',
  rounded = 'rounded-md',
}) => (
  <div className={`${width} ${height} ${rounded} bg-gray-200 animate-pulse ${className}`} />
);

// Text line skeleton
export const SkeletonText: React.FC<{ lines?: number; className?: string }> = ({
  lines = 3,
  className = '',
}) => (
  <div className={`space-y-2.5 ${className}`}>
    {Array.from({ length: lines }).map((_, i) => (
      <Skeleton key={i} width={i === lines - 1 ? 'w-2/3' : 'w-full'} height="h-3.5" />
    ))}
  </div>
);

// Card skeleton for report loading
export const SkeletonCard: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`p-5 rounded-xl border border-gray-100 space-y-4 ${className}`}>
    <div className="flex items-center gap-3">
      <Skeleton width="w-10" height="h-10" rounded="rounded-lg" />
      <div className="flex-1 space-y-2">
        <Skeleton width="w-1/3" height="h-4" />
        <Skeleton width="w-1/2" height="h-3" />
      </div>
    </div>
    <SkeletonText lines={4} />
  </div>
);

// Score bar skeleton
export const SkeletonScoreBar: React.FC = () => (
  <div className="space-y-3">
    {Array.from({ length: 6 }).map((_, i) => (
      <div key={i} className="flex items-center gap-3">
        <Skeleton width="w-16" height="h-3" />
        <Skeleton width="w-full" height="h-2.5" rounded="rounded-full" />
        <Skeleton width="w-8" height="h-3" />
      </div>
    ))}
  </div>
);
