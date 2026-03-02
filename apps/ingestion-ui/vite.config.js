import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:31800',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/lightrag': {
        target: 'http://localhost:31436',
        rewrite: (path) => path.replace(/^\/lightrag/, ''),
      },
    },
  },
});
