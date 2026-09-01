import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      // local dev: vite on :5173 proxies API calls to uvicorn on :8000
      "/ask": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
