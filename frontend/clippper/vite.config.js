import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'

// https://vite.dev/config/
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000', //fastapi backend
        changeOrigin: true,
      },
    },
  },

  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] })
  ],
})
