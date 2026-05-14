/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'cyan': {
          DEFAULT: '#2563eb',
          dim: '#1d4ed8',
          glow: 'rgba(37, 99, 235, 0.15)',
        },
        'purple': {
          DEFAULT: '#6366f1',
          dim: '#4f46e5',
          glow: 'rgba(99, 102, 241, 0.12)',
        },
        'success': '#16a34a',
        'warning': '#d97706',
        'danger': '#dc2626',
        'base': '#f8fafc',
        'card': '#ffffff',
        'elevated': '#f1f5f9',
        'hover': '#e2e8f0',
        'primary': '#0f172a',
        'secondary': '#475569',
        'muted': '#94a3b8',
        'border': {
          dim: 'rgba(0, 0, 0, 0.04)',
          DEFAULT: 'rgba(0, 0, 0, 0.08)',
          accent: 'rgba(37, 99, 235, 0.3)',
          purple: 'rgba(99, 102, 241, 0.25)',
        },
      },
      backgroundImage: {
        'gradient-purple-cyan': 'linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(37, 99, 235, 0.05) 100%)',
        'gradient-card-border': 'linear-gradient(180deg, rgba(99, 102, 241, 0.15) 0%, rgba(99, 102, 241, 0.05) 50%, rgba(37, 99, 235, 0.08) 100%)',
        'gradient-cyan': 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
      },
      boxShadow: {
        'glow-cyan': '0 2px 12px rgba(37, 99, 235, 0.15)',
        'glow-purple': '0 2px 12px rgba(99, 102, 241, 0.12)',
        'glow-success': '0 2px 12px rgba(22, 163, 74, 0.15)',
        'glow-danger': '0 2px 12px rgba(220, 38, 38, 0.15)',
        'subtle': '0 1px 2px 0 rgba(0, 0, 0, 0.03)',
        'medium': '0 2px 8px -2px rgba(0, 0, 0, 0.08), 0 4px 12px -4px rgba(0, 0, 0, 0.05)',
        'strong': '0 8px 24px -8px rgba(0, 0, 0, 0.12), 0 12px 40px -12px rgba(0, 0, 0, 0.08)',
      },
      borderRadius: {
        'xl': '12px',
        '2xl': '16px',
        '3xl': '20px',
      },
      fontSize: {
        'xxs': '10px',
        'label': '11px',
        'heading-xl': ['1.5rem', { lineHeight: '1.2', fontWeight: '700' }],
        'heading-lg': ['1.25rem', { lineHeight: '1.3', fontWeight: '600' }],
        'heading-md': ['1rem', { lineHeight: '1.4', fontWeight: '600' }],
        'heading-sm': ['0.875rem', { lineHeight: '1.4', fontWeight: '600' }],
        'body': ['0.875rem', { lineHeight: '1.6', fontWeight: '400' }],
        'body-sm': ['0.8125rem', { lineHeight: '1.5', fontWeight: '400' }],
        'caption': ['0.75rem', { lineHeight: '1.4', fontWeight: '400' }],
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
        'section': '2rem',
        'card-padding': '1.5rem',
        'block-gap': '1rem',
        'item-gap': '0.75rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'spin-slow': 'spin 2s linear infinite',
      },
      transitionDuration: {
        quick: '150ms',
        normal: '300ms',
        slow: '500ms',
      },
      minHeight: {
        touch: '44px',
      },
      minWidth: {
        touch: '44px',
      },
      keyframes: {
        fadeIn: {
          'from': { opacity: '0' },
          'to': { opacity: '1' },
        },
        slideUp: {
          'from': { opacity: '0', transform: 'translateY(10px)' },
          'to': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          'from': { opacity: '0', transform: 'translateX(100%)' },
          'to': { opacity: '1', transform: 'translateX(0)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 12px rgba(37, 99, 235, 0.15)' },
          '50%': { boxShadow: '0 0 24px rgba(37, 99, 235, 0.25)' },
        },
      },
    },
  },
  plugins: [],
}
