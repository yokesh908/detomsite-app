/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}', './mobile/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#15803D',
          dark: '#166534',
          light: '#DCFCE7',
        },
        gold: {
          DEFAULT: '#D4A017',
          light: '#FEF3C7',
          dark: '#A16207',
        },
        surface: '#FFFFFF',
        border: '#E2E8F0',
        divider: '#F1F5F9',
        text: {
          primary: '#111827',
          secondary: '#64748B',
          muted: '#94A3B8',
        },
        status: {
          success: '#16A34A',
          'success-bg': '#DCFCE7',
          warning: '#D97706',
          'warning-bg': '#FEF3C7',
          error: '#DC2626',
          'error-bg': '#FEE2E2',
          info: '#2563EB',
          'info-bg': '#DBEAFE',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'sans-serif'],
      },
      boxShadow: {
        'card': '0 1px 3px rgba(15, 23, 42, 0.06)',
        'card-hover': '0 4px 12px rgba(15, 23, 42, 0.08)',
        'modal': '0 12px 32px rgba(15, 23, 42, 0.14)',
        'dropdown': '0 8px 24px rgba(15, 23, 42, 0.12)',
        'toast': '0 8px 24px rgba(15, 23, 42, 0.12)',
      },
      borderRadius: {
        'sm': '6px',
        'btn': '8px',
        'input': '8px',
        'card': '12px',
        'panel': '16px',
        'pill': '9999px',
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
        '112': '28rem',
        '128': '32rem',
        '144': '36rem',
      },
      maxWidth: {
        'content': '1280px',
      },
      fontSize: {
        'heading-h1': ['32px', { lineHeight: '40px', fontWeight: '700' }],
        'heading-h2': ['24px', { lineHeight: '32px', fontWeight: '700' }],
        'heading-h3': ['20px', { lineHeight: '28px', fontWeight: '600' }],
        'body': ['15px', { lineHeight: '24px', fontWeight: '400' }],
        'small': ['13px', { lineHeight: '20px', fontWeight: '400' }],
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out forwards',
        'slide-up': 'slideUp 0.2s ease-out forwards',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
