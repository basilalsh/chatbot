import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    proxy: {
      "/ask": "http://127.0.0.1:5000",
      "/ask-stream": "http://127.0.0.1:5000",
      "/upload": "http://127.0.0.1:5000",
    },
  },
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
  },
});
