import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Production assets are written to ../web/dist and served by the FastAPI process; the development server proxies the API.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {outDir: '../web/dist', emptyOutDir: true, assetsDir: 'assets', sourcemap: false, chunkSizeWarningLimit: 1500},
  server: {port: 5173, proxy: {'/api': 'http://127.0.0.1:8765'}},
  test: {environment: 'jsdom', include: ['src/**/*.test.ts', 'src/**/*.test.tsx'], globals: false},
});
