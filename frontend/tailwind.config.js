/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        panel: '#0f172a',
        accent: '#3b82f6',
        success: '#22c55e',
        warning: '#f59e0b',
        danger: '#ef4444',
      },
    },
  },
  plugins: [],
};
