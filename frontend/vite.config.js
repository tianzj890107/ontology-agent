import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Keep the initial application chunk focused on the workbench code.
        // Excel is already loaded on demand; split the stable UI runtimes so
        // they can be cached independently across both service entry points.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("xlsx")) return "xlsx";
          if (id.includes("react") || id.includes("antd") || id.includes("@ant-design") || id.includes("rc-")) return "ui";
          // Leave unrelated dependencies with their importing feature to
          // avoid a circular vendor -> react -> vendor chunk graph.
          return undefined;
        },
      },
    },
  },
});
