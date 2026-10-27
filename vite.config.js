import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { readConfig } from './src/data/capabilities.js'
import { readOnlyGateway, validateProxyTarget } from './config/devProxy.js'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const config = readConfig(env)
  const target = validateProxyTarget(env.NMS_API_TARGET)
  if (config.invalid) throw new Error('VITE_NMS_API_BASE must be a same-origin path')
  if (target && !config.base) throw new Error('A non-root API prefix is required for the development gateway')
  return {
    plugins: [react(), ...(target ? [readOnlyGateway(config.base)] : [])],
    resolve: { alias: {
      '~bootstrap': fileURLToPath(new URL('./node_modules/bootstrap', import.meta.url)),
      '~bootstrap-icons': fileURLToPath(new URL('./node_modules/bootstrap-icons', import.meta.url)),
    } },
    // The archived HTML demos are reference sources, not React application entries.
    optimizeDeps: { entries: ['index.html'] },
    css: { preprocessorOptions: { scss: { quietDeps: true, silenceDeprecations: ['import', 'global-builtin', 'color-functions', 'if-function'] } } },
    server: {
      host: '127.0.0.1', port: 5173, strictPort: true,
      proxy: target ? { [config.base]: {
        target, changeOrigin: true, secure: true, timeout: 10000, proxyTimeout: 10000,
        rewrite: (path) => path.slice(config.base.length),
        configure(proxy) {
          proxy.on('proxyReq', (request, incoming) => {
            if (incoming.headers.origin) request.setHeader('Origin', target)
            request.removeHeader('Authorization')
          })
          proxy.on('error', (_error, _request, response) => {
            if (!response.headersSent && typeof response.writeHead === 'function') {
              response.writeHead(502, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); response.end('{"error":"backend_unavailable"}')
            }
          })
        },
      } } : undefined,
    },
  }
})
