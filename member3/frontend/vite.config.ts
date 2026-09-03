import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
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
      // Exclude the AgathSethu git repo subfolder and large media files
      // from Vite's file watcher to prevent EBUSY errors on MP4 files
      ignored: [
        '**/AgathSethu/**',
        '**/*.mp4',
        '**/*.mkv',
        '**/node_modules/**',
        '**/dist/**',
      ],
    },
  },
})
