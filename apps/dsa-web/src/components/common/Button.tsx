import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'gradient' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  /** Show loading spinner. Alias: isLoading */
  loading?: boolean;
  /** @deprecated Use `loading` instead */
  isLoading?: boolean;
  glow?: boolean;
  children: React.ReactNode;
}

const variantClasses: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary:
    'bg-gradient-to-r from-cyan to-cyan-dim text-white shadow-sm hover:shadow-md hover:shadow-cyan/20',
  secondary:
    'border border-border bg-transparent text-primary hover:bg-elevated/80',
  ghost: 'text-secondary hover:text-primary hover:bg-elevated/60',
  outline:
    'bg-transparent text-cyan border border-border-accent hover:bg-cyan/5 hover:border-cyan',
  gradient:
    'bg-gradient-to-r from-cyan to-cyan-dim text-white hover:from-cyan/90 hover:to-cyan-dim/90 shadow-lg shadow-glow-cyan',
  danger:
    'bg-red-600 text-white hover:bg-red-500 shadow-lg shadow-red-500/25',
};

const sizeClasses: Record<NonNullable<ButtonProps['size']>, string> = {
  sm: 'h-7 px-3 text-xs rounded-lg gap-1.5',
  md: 'h-9 px-4 text-sm rounded-xl gap-2',
  lg: 'h-11 px-6 text-base rounded-xl gap-2.5',
};

/**
 * Button component
 * Supports multiple variants, sizes, loading state, and glow effect.
 */
export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  loading,
  isLoading,
  glow = false,
  className = '',
  disabled,
  ...props
}) => {
  const isInLoading = loading ?? isLoading ?? false;

  const baseClasses = [
    'inline-flex items-center justify-center font-medium',
    'transition-all duration-200',
    'focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-base',
    'active:scale-[0.97]',
    'disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100',
  ].join(' ');

  const glowClasses = glow
    ? 'shadow-glow-cyan hover:shadow-[0_0_30px_rgba(6,182,212,0.4)]'
    : '';

  const classes = [
    baseClasses,
    sizeClasses[size],
    variantClasses[variant],
    glowClasses,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <button
      className={classes}
      disabled={disabled || isInLoading}
      {...props}
    >
      {isInLoading && (
        <svg
          className="animate-spin h-4 w-4 text-current shrink-0"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      )}
      <span className={isInLoading ? 'opacity-70' : ''}>{children}</span>
    </button>
  );
};
