import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Shown as "Last updated" in the public footer: the date this build was made.
  define: {
    __APP_LAST_UPDATED__: JSON.stringify(new Date().toISOString().slice(0, 10)),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@components': path.resolve(__dirname, './src/components'),
      '@stores': path.resolve(__dirname, './src/stores'),
      '@hooks': path.resolve(__dirname, './src/hooks'),
      '@api': path.resolve(__dirname, './src/api'),
      '@services': path.resolve(__dirname, './src/services'),
      '@integrations': path.resolve(__dirname, './src/integrations'),
      '@types': path.resolve(__dirname, './src/types'),
      '@theme': path.resolve(__dirname, './src/theme'),
      '@utils': path.resolve(__dirname, './src/utils'),
      '@routes': path.resolve(__dirname, './src/routes'),
      '@pages': path.resolve(__dirname, './src/pages'),
    },
  },
  server: {
    port: 5173,
    open: true,
    watch: {
      // Exclude large media files from Vite's file watcher to prevent EBUSY
      // errors on MP4 files. (A '**/AgathSethu/**' entry used to be here; the
      // project itself lives under AgathSethu/, so it hid every source change.)
      ignored: [
        '**/*.mp4',
        '**/*.mkv',
        '**/node_modules/**',
        '**/dist/**',
      ],
    },
  },
})
