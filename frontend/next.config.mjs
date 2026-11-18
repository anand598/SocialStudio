import path from "node:path";
import { fileURLToPath } from "node:url";

export default {
  output: "standalone",
  experimental: {
    // Uploads go through the /api rewrite below. Next.js truncates proxied bodies at 10 MB by
    // default, which broke video uploads. This must cover the API's largest request (video, music
    // and logo plus form overhead: 123 MB by default; backend/tests/test_upload.py checks it).
    // The API still enforces the real per-type limits.
    middlewareClientMaxBodySize: "125mb",
  },
  async rewrites() {
    const upstream = (process.env.API_PROXY_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${upstream}/api/:path*` }];
  },
  outputFileTracingRoot: path.dirname(fileURLToPath(import.meta.url)),
};
