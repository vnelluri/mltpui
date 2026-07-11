import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Light theme. The semantic names are historical (bg-dark = page
      // background, bg-card = surface, bg-elevated = borders/hover fills) —
      // every component styles against these tokens, so the palette lives
      // here and in globals.css only. The login hero deliberately stays on
      // brand-valhalla (dark) as a branded surface.
      colors: {
        brand: {
          // Darkened from the on-dark accent (#A6A3E0) so it reads on white.
          purple: '#6C63C5',
          valhalla: '#2E1A47',
          white: '#FFFFFF',
        },
        bg: {
          dark: '#F4F3FA',
          card: '#FFFFFF',
          elevated: '#E8E5F2',
        },
        text: {
          primary: '#241E3D',
          secondary: '#5A5280',
          muted: '#8D86AD',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      borderColor: {
        DEFAULT: '#E8E5F2',
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'spin-slow': {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.2s ease-out',
        'spin-slow': 'spin-slow 1s linear infinite',
      },
    },
  },
  plugins: [],
};

export default config;
