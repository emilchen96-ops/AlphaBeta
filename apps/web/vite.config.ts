import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: "react-vendor",
              test: /node_modules[\\/](react|react-dom|react-router-dom|@tanstack)[\\/]/,
              priority: 30,
            },
            {
              name: "antd-vendor",
              test: /node_modules[\\/](@ant-design|antd|rc-)/,
              priority: 20,
              maxSize: 450 * 1024,
            },
            {
              name: "vendor",
              test: /node_modules[\\/]/,
              priority: 10,
              maxSize: 450 * 1024,
            },
          ],
        },
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    clearMocks: true,
    maxWorkers: 2,
    testTimeout: 10_000,
  },
});
