import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'

// https://vite.dev/config/
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.js'],
    env: { VITE_API_URL: 'http://api.test' },
    coverage: { include: ["src/lib/**", "src/services/*.js"], reporter: ['text'] },
  },

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
