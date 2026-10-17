import http from 'node:http'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, type Plugin } from 'vite'

const DEV_PORT = 5173
// Supabase's Site URL defaults to localhost:3000, so sign-in links aimed at the
// stock project configuration land on a port nothing serves ("This site can't
// be reached"). Mirror the dev server there instead of requiring a dashboard
// change. Set VITE_ALIAS_PORT=0 to disable.
const ALIAS_PORT = Number(process.env.VITE_ALIAS_PORT ?? 3000)

/**
 * Forwards :3000 to the dev server. The Location header carries the path and
 * query but no fragment, so the browser keeps the original `#access_token=…`
 * that Supabase appends — the SPA can then redeem it as usual.
 */
function loopbackAlias(from: number, to: number): Plugin {
  return {
    name: 'loopback-port-alias',
    apply: 'serve',
    configureServer(server) {
      const live = new Set<http.Server>()
      let stopped = false

      const handler: http.RequestListener = (req, res) => {
        const url = new URL(req.url ?? '/', 'http://localhost')
        res.writeHead(307, {
          Location: `http://localhost:${to}${url.pathname}${url.search}`,
          'Cache-Control': 'no-store',
        })
        res.end()
      }

      // Both loopback families: a Site URL written as 127.0.0.1 must answer
      // too, and "localhost" only covers whichever stack resolves first.
      // A config edit restarts the dev server in place, so the previous
      // listeners can still hold the port for a moment — retry briefly.
      const bind = (address: string, attempt = 0) => {
        if (stopped) return
        const listener = http.createServer(handler)
        listener.once('listening', () => live.add(listener))
        listener.once('error', (err: NodeJS.ErrnoException) => {
          if ((err.code === 'EADDRINUSE' || err.code === 'EADDRNOTAVAIL') && attempt < 8) {
            setTimeout(() => bind(address, attempt + 1), 150)
            return
          }
          server.config.logger.warn(
            `alias ${address}:${from} unavailable (${err.code}) — links to :${to} still work`,
          )
        })
        listener.listen(from, address)
      }

      bind('127.0.0.1')
      bind('::1')
      server.httpServer?.once('close', () => {
        stopped = true
        live.forEach((listener) => listener.close())
        live.clear()
      })
    },
  }
}

// Dev proxy: the frontend talks to the FastAPI backend on :8000
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    ...(ALIAS_PORT && ALIAS_PORT !== DEV_PORT ? [loopbackAlias(ALIAS_PORT, DEV_PORT)] : []),
  ],
  server: {
    port: DEV_PORT,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
})
