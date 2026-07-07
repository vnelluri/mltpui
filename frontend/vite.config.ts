import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true,
    port: 3000,
    watch: {
      // Docker Desktop on Windows doesn't reliably forward bind-mount file
      // change events into the container's inotify watches, so Vite's
      // default watcher silently never fires. Polling is slower but works
      // regardless of host OS / filesystem driver.
      usePolling: true,
      interval: 300,
    },
  },
  preview: {
    host: true,
    port: 3000,
  },
});
