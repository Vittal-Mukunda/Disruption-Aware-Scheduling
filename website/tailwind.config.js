/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary:    'hsl(218, 73%, 35%)',
        accent:     'hsl(262, 80%, 65%)',
        secondary:  'hsl(218, 45%, 52%)',
        background: 'hsl(210, 40%, 98%)',
        foreground: 'hsl(218, 30%, 12%)',
        muted:      'hsl(215, 20%, 93%)',
        'muted-foreground': 'hsl(218, 15%, 45%)',
        border:     'hsl(215, 18%, 86%)',
      },
      fontFamily: {
        heading: ['Nunito', 'serif'],
        body:    ['Nunito', 'sans-serif'],
      },
      boxShadow: {
        soft: '0 4px 24px -6px rgba(30,58,138,0.12)',
        glow: '0 0 20px rgba(30,58,138,0.2)',
      },
    },
  },
  plugins: [],
};
