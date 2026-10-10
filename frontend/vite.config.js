import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1' },
  preview: { host: '127.0.0.1' },
  build: {
    rollupOptions: {
      output: {
        // Stable vendor code in separate, long-cached chunks; the app chunk alone exceeded
        // Vite's 500 kB warning (chart.js ~170 kB + react-dom ~127 kB). Same code loads at startup.
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-charts': ['chart.js', 'react-chartjs-2'],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
    css: true,
    restoreMocks: true,
    testTimeout: 20000,
    hookTimeout: 10000,
  },
});
