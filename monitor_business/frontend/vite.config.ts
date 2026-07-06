import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Default matches docker-compose: monitor-service publishes 18080; api-gateway uses 8080 (override via .env.development).
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:18080'

  const apiProxy = {
    // Browser hits Vite only; /api/* is forwarded to Spring (or gateway) by Node.
    // Use localhost instead of 127.0.0.1: on some macOS/JDK setups Spring binds to ::1 only and IPv4 proxy fails.
    '/api': {
      target: apiProxyTarget,
      changeOrigin: true,
      // "Run batch now" calls AI synchronously; often exceeds default proxy timeout
      timeout: 1_800_000,
      proxyTimeout: 1_800_000,
    },
  }

  return {
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
  }
})
