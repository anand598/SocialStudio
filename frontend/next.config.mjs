import path from "node:path";
import { fileURLToPath } from "node:url";

export default {
  output: "standalone",
  async rewrites() {
    const upstream = (process.env.API_PROXY_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${upstream}/api/:path*` }];
  },
  outputFileTracingRoot: path.dirname(fileURLToPath(import.meta.url)),
};
