import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

// 本番はリバースプロキシ配下で稼働するため、外部ホスト名を許可する。
// VITE_ALLOWED_HOSTS=true で全許可、またはカンマ区切りでホスト名を指定。
const allowedHosts =
  process.env.VITE_ALLOWED_HOSTS === 'true'
    ? true
    : process.env.VITE_ALLOWED_HOSTS
      ? process.env.VITE_ALLOWED_HOSTS.split(',')
      : undefined;

// https://vitejs.dev/config/
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      './runtimeConfig': './runtimeConfig.browser',
    },
  },
  // Open GENAI: Docker コンテナ内から起動するため 0.0.0.0 で待ち受け、
  // バインドマウント上でも HMR が効くようファイル監視をポーリングにする。
  server: {
    host: true,
    port: 5173,
    allowedHosts,
    fs: {
      // packages/web/.env 等を Vite が読めるようにモノレポ根まで許可
      allow: [path.resolve(__dirname, '../..')],
    },
    watch: {
      usePolling: process.env.VITE_USE_POLLING === 'true',
    },
  },
  preview: {
    host: true,
    port: 5173,
    allowedHosts,
  },
  plugins: [
    react(),
    tailwindcss(),
  ],
});
