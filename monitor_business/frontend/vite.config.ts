import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxy = {
  // Browser hits Vite only; /api/* is forwarded to Spring by Node.
  // Use localhost instead of 127.0.0.1: on some macOS/JDK setups Spring binds to ::1 only and IPv4 proxy fails.
  '/api': {
    target: 'http://localhost:8080',
    changeOrigin: true,
    // "Run batch now" calls AI synchronously; often exceeds default proxy timeout
    timeout: 1_800_000,
    proxyTimeout: 1_800_000,
  },
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: apiProxy,
  },
  // `npm run preview` does not use server.proxy by default; without this, /api never reaches Spring (Network Error in browser).
  preview: {
    proxy: apiProxy,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/recharts')) {
            return 'recharts'
          }
          if (id.includes('node_modules/leaflet') || id.includes('node_modules/react-leaflet')) {
            return 'map'
          }
        },
      },
    },
  },
})
