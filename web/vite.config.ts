import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";

// Multi-page: the map at / and the researcher screen at /researchers/ (its own HTML entry,
// reached through the "Researcher view" toggle and its interstitial).
const page = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const input: Record<string, string> = {
  main: page("./index.html"),
  researchers: page("./researchers/index.html"),
};

// `vite preview` serves the production build with the same headers vercel.json sets for every
// path, so the CSP is tested against the real bundle before a deploy.
const vercel = JSON.parse(readFileSync(page("./vercel.json"), "utf8")) as {
  headers: { source: string; headers: { key: string; value: string }[] }[];
};
const previewHeaders = Object.fromEntries(
  (vercel.headers.find((h) => h.source === "/(.*)")?.headers ?? []).map((h) => [h.key, h.value]),
);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true, host: "127.0.0.1" },
  preview: { port: 4173, strictPort: true, host: "127.0.0.1", headers: previewHeaders },
  build: { rollupOptions: { input }, chunkSizeWarningLimit: 1500 },
});
