import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
import { createChunkFileName } from './config/chunkNaming.js';

function getPackageName(id) {
  const normalized = String(id || '').replace(/\\/g, '/');
  const [, afterNodeModules = ''] = normalized.split('/node_modules/');
  if (!afterNodeModules) return '';

  const resolved = afterNodeModules.startsWith('.pnpm/')
    ? afterNodeModules.split('/node_modules/').at(-1) || ''
    : afterNodeModules;

  if (resolved.startsWith('@')) {
    const [scope, name] = resolved.split('/');
    return scope && name ? `${scope}/${name}` : resolved;
  }

  return resolved.split('/')[0] || '';
}

function buildManualChunk(id) {
  if (id.includes('node_modules')) {
    const packageName = getPackageName(id);

    if (packageName === 'react' || packageName === 'react-dom' || packageName === 'scheduler') {
      return 'vendor-react';
    }

    if (packageName === '@ant-design/icons' || packageName === '@ant-design/icons-svg') {
      return 'vendor-antd-icons';
    }

    if (packageName === 'recharts' || packageName === 'victory-vendor' || packageName.startsWith('d3-')) {
      return 'vendor-charts';
    }

    if (packageName === 'dayjs' || packageName === 'zustand') {
      return 'vendor-utils';
    }

    return undefined;
  }

  return undefined;
}

export default defineConfig({
  base: '/static/app-shell/',
  plugins: [react()],
  publicDir: false,
  build: {
    outDir: resolve(__dirname, '../static/app-shell'),
    emptyOutDir: true,
    cssCodeSplit: false,
    sourcemap: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/main.jsx'),
      output: {
        entryFileNames: 'beacon-shell.js',
        chunkFileNames: createChunkFileName,
        manualChunks: buildManualChunk,
        assetFileNames: (assetInfo) => {
          const name = assetInfo.name || '';
          if (name.endsWith('.css')) {
            return 'beacon-shell.css';
          }
          return 'assets/[name]-[hash][extname]';
        },
      },
    },
  },
  server: {
    proxy: {
      '/__beacon_backend': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/__beacon_backend/, ''),
      },
      '/api': 'http://127.0.0.1:9991',
      '/alarm': 'http://127.0.0.1:9991',
      '/control': 'http://127.0.0.1:9991',
      '/stream': 'http://127.0.0.1:9991',
      // Keep backend static endpoints proxied in dev, but let Vite serve the
      // app-shell base path itself so /static/app-shell/ does not 404 locally.
      '^/static/(?!app-shell(?:/|$))': 'http://127.0.0.1:9991',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    testTimeout: 20000,
  },
});
