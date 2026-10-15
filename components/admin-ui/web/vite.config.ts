import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': new URL('./src', import.meta.url).pathname } },
  server: { proxy: { '/api': 'http://127.0.0.1:3000', '/sign-out': 'http://127.0.0.1:3000', '/fonts': 'http://127.0.0.1:3000' } },
})
