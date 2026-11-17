import { describe, expect, it } from "vitest";
import nextConfig from "../next.config.mjs";

// The browser uploads through the Next.js /api rewrite. Next buffers proxied bodies up to
// middlewareClientMaxBodySize (default 10 MB) and silently truncates the rest, so the limit
// must cover the backend's largest accepted upload (MAX_VIDEO_UPLOAD_SIZE_MB, default 100).
describe("API proxy body limit", () => {
  it("lets a maximum-size video upload through", () => {
    const limit = String(
      nextConfig.experimental?.middlewareClientMaxBodySize ?? "10mb",
    );
    const match = /^(\d+)mb$/i.exec(limit);
    expect(match, `unexpected size format: ${limit}`).not.toBeNull();
    expect(Number(match![1])).toBeGreaterThan(100);
  });
});
