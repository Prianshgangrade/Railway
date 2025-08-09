import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// You don't need the tailwindcss import here if you're following standard setup
// It's usually configured in postcss.config.js

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(),tailwindcss()],
  server: {
    // This `watch` object is where `ignored` should be.
    // This fixes the "browser reloading" issue.
    watch: {
      ignored: ['**/api/**'],
    },
    // The `proxy` object tells Vite to redirect API requests.
    // This fixes potential CORS issues and simplifies frontend fetch calls.
    proxy: {
      // Any request from your frontend that starts with "/api"
      // will be forwarded to your Python backend at http://127.0.0.1:5000
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
});