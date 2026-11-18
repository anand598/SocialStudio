import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import Home from "./page";

const id = "11111111-1111-4111-8111-111111111111";
const config = {
  formats: [
    {
      platform: "instagram",
      platform_label: "Instagram",
      format: "reel",
      label: "Instagram Reel",
      kind: "video",
      width: 1080,
      height: 1920,
      aspect_ratio: "9:16",
      description: "Vertical MP4 for Reels",
    },
    {
      platform: "instagram",
      platform_label: "Instagram",
      format: "feed_square",
      label: "Instagram Square Post (1:1)",
      kind: "image",
      width: 1080,
      height: 1080,
      aspect_ratio: "1:1",
      description: "Square JPEG for the feed",
    },
    {
      platform: "tiktok",
      platform_label: "TikTok",
      format: "video",
      label: "TikTok Video",
      kind: "video",
      width: 1080,
      height: 1920,
      aspect_ratio: "9:16",
      description: "Vertical MP4",
    },
    {
      platform: "youtube",
      platform_label: "YouTube",
      format: "thumbnail",
      label: "YouTube Thumbnail",
      kind: "image",
      width: 1280,
      height: 720,
      aspect_ratio: "16:9",
      description: "1280 × 720 JPEG thumbnail",
    },
  ],
  input_types: ["image", "video", "url"],
  generation_mode: "demo",
  max_upload_size_mb: 15,
  max_video_upload_size_mb: 100,
  max_source_video_seconds: 180,
  max_music_upload_size_mb: 20,
  max_music_seconds: 600,
};
const job = {
  id,
  status: "completed",
  stage: "completed",
  input_type: "image",
  platform: "instagram",
  format: "reel",
  output_kind: "video",
  post_text: null as string | null,
  generation_mode: "demo",
  error_message: null,
  product_analysis: null,
  generated_content: {
    hook: "Look closer",
    caption: "Demo caption",
    call_to_action: "Shop",
    hashtags: ["#Demo"],
    disclaimer_or_assumptions: "Demo copy; review before publishing.",
  },
};
function mockFetch(
  result: Omit<typeof job, "error_message"> & {
    error_message: string | null;
  } = job,
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    return new Response(
      JSON.stringify(
        url.endsWith("/config/platforms")
          ? config
          : url.includes("/generations?")
            ? { items: [] }
            : result,
      ),
      { status: 200 },
    );
  });
}

describe("creative workflow", () => {
  it("labels demo mode and validates uploads before submitting", async () => {
    mockFetch();
    render(<Home />);
    expect(await screen.findByText("Demo mode is on.")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create my Instagram Reel/ }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Product image"), {
      target: { files: [new File(["x"], "file.txt", { type: "text/plain" })] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose a JPEG, PNG, or WebP image.",
    );
  });
  it("restores a completed job with preview, download and caption after refresh", async () => {
    window.history.replaceState(null, "", `#job=${id}`);
    mockFetch();
    render(<Home />);
    expect(
      await screen.findByRole("link", { name: /Download Instagram Reel/ }),
    ).toHaveAttribute("href", expect.stringContaining(id));
    expect(screen.getByLabelText("Generated Instagram Reel")).toHaveAttribute(
      "src",
      expect.stringContaining("/preview"),
    );
    expect(screen.getByLabelText("Caption & hashtags")).toHaveValue(
      "Demo caption\n\nShop\n\n#Demo",
    );
    expect(
      screen.getByText("Demo copy; review before publishing."),
    ).toBeInTheDocument();
  });
  it("shows queued state and submits the chosen image and format", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:sample");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const fetch = mockFetch({ ...job, status: "queued", stage: "validating" });
    render(<Home />);
    await screen.findByText("Demo mode is on.");
    const image = new File(["test"], "product.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Product image"), {
      target: { files: [image] },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Create my Instagram Reel/ }),
    );
    expect(
      await screen.findByText("Your request is in the queue."),
    ).toBeInTheDocument();
    const call = fetch.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/generations") && init?.method === "POST",
    );
    const data = call?.[1]?.body as FormData;
    expect(data.get("file")).toBe(image);
    expect(data.get("input_type")).toBe("image");
    expect(data.get("platform")).toBe("instagram");
    expect(data.get("format")).toBe("reel");
  });
  it("shows a safe failure and retry action", async () => {
    window.history.replaceState(null, "", `#job=${id}`);
    mockFetch({
      ...job,
      status: "failed",
      error_message: "Check the worker and retry.",
    });
    render(<Home />);
    expect(
      await screen.findByText("Check the worker and retry."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Retry generation/ }),
    ).toBeEnabled();
  });
});

it("polls from queued through rendering to completion", async () => {
  window.history.replaceState(null, "", `#job=${id}`);
  let statusReads = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    let result: unknown = config;
    if (String(input).includes("/generations?")) {
      result = { items: [] };
    } else if (!String(input).endsWith("/config/platforms")) {
      statusReads += 1;
      result =
        statusReads === 1
          ? { ...job, status: "queued", stage: "validating" }
          : statusReads === 2
            ? { ...job, status: "processing", stage: "rendering" }
            : job;
    }
    return new Response(JSON.stringify(result), { status: 200 });
  });
  render(<Home />);
  expect(
    await screen.findByText("Your request is in the queue."),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole(
      "heading",
      { name: "Render your video" },
      { timeout: 4000 },
    ),
  ).toBeInTheDocument();
  expect(
    await screen.findByText(
      "Your product, ready to play.",
      {},
      { timeout: 4000 },
    ),
  ).toBeInTheDocument();
  expect(statusReads).toBe(3);
}, 10000);

describe("inputs, platforms and formats", () => {
  it("filters formats by platform and submits a product URL", async () => {
    const fetch = mockFetch({
      ...job,
      status: "processing",
      stage: "fetching",
      input_type: "url",
      platform: "youtube",
      format: "thumbnail",
      output_kind: "image",
    });
    render(<Home />);
    await screen.findByText("Demo mode is on.");
    fireEvent.change(screen.getByLabelText("Platform"), {
      target: { value: "youtube" },
    });
    const format = screen.getByLabelText("Format");
    expect(
      within(format)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Thumbnail · 16:9"]);
    expect(screen.getByText(/1280 × 720 · JPEG image/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Product URL/ }));
    const button = screen.getByRole("button", {
      name: /Create my YouTube Thumbnail/,
    });
    const url = screen.getByLabelText(/Product page URL/);
    fireEvent.change(url, { target: { value: "not a url" } });
    expect(button).toBeDisabled();
    expect(
      screen.getByText("Enter a full http:// or https:// address."),
    ).toBeInTheDocument();
    fireEvent.change(url, {
      target: { value: "https://shop.example.com/lamp" },
    });
    fireEvent.click(button);
    expect(
      await screen.findByRole("heading", { name: "Read the product page" }),
    ).toBeInTheDocument();
    const call = fetch.mock.calls.find(
      ([target, init]) =>
        String(target).endsWith("/generations") && init?.method === "POST",
    );
    const data = call?.[1]?.body as FormData;
    expect(data.get("input_type")).toBe("url");
    expect(data.get("source_url")).toBe("https://shop.example.com/lamp");
    expect(data.get("file")).toBeNull();
    expect(data.get("platform")).toBe("youtube");
    expect(data.get("format")).toBe("thumbnail");
  });

  it("accepts videos only on the video tab", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:clip");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    mockFetch();
    render(<Home />);
    await screen.findByText("Demo mode is on.");
    fireEvent.click(screen.getByRole("tab", { name: /Video/ }));
    const field = screen.getByLabelText("Product video");
    fireEvent.change(field, {
      target: {
        files: [new File(["x"], "a.png", { type: "image/png" })],
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose an MP4, MOV, or WebM video.",
    );
    fireEvent.change(field, {
      target: {
        files: [new File(["x"], "clip.mp4", { type: "video/mp4" })],
      },
    });
    expect(screen.getByLabelText("Selected product video")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Create my Instagram Reel/ }),
    ).toBeEnabled();
  });

  it("previews image results and shows platform post text", async () => {
    window.history.replaceState(null, "", `#job=${id}`);
    mockFetch({
      ...job,
      platform: "youtube",
      format: "thumbnail",
      output_kind: "image",
      post_text: "Title: Lamp\n\nDemo caption\n\nShop\n\n#Demo",
    });
    render(<Home />);
    const preview = await screen.findByRole("img", {
      name: "Generated YouTube Thumbnail",
    });
    expect(preview).toHaveAttribute("src", expect.stringContaining("/preview"));
    expect(
      screen.getByRole("link", { name: /Download YouTube Thumbnail/ }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Title, description & hashtags")).toHaveValue(
      "Title: Lamp\n\nDemo caption\n\nShop\n\n#Demo",
    );
  });
});

it("shows field-level details from API validation errors", async () => {
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:sample");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method === "POST")
      return new Response(
        JSON.stringify({
          detail: [
            {
              type: "missing",
              loc: ["body", "file"],
              msg: "Field required",
              input: null,
            },
          ],
        }),
        { status: 422 },
      );
    return new Response(JSON.stringify(config), { status: 200 });
  });
  render(<Home />);
  await screen.findByText("Demo mode is on.");
  fireEvent.change(screen.getByLabelText("Product image"), {
    target: { files: [new File(["x"], "p.png", { type: "image/png" })] },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /Create my Instagram Reel/ }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The server rejected the request: file — Field required.",
  );
});

it("follows #job changes without a reload (back/forward between jobs)", async () => {
  window.history.replaceState(null, "", "/");
  const other = "22222222-2222-4222-8222-222222222222";
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/config/platforms"))
      return new Response(JSON.stringify(config), { status: 200 });
    return new Response(
      JSON.stringify({ ...job, id: url.includes(other) ? other : id }),
      { status: 200 },
    );
  });
  render(<Home />);
  await screen.findByText("Demo mode is on.");
  window.location.hash = `job=${other}`;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(
    await screen.findByText(`Generation ${other}`, {}, { timeout: 4000 }),
  ).toBeInTheDocument();
  // Back to a URL without #job returns to the empty studio.
  window.history.replaceState(null, "", "/");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(
    await screen.findByText("A blank canvas. A world of possibility."),
  ).toBeInTheDocument();
});

it("lists this browser's recent creatives and opens one from the list", async () => {
  const earlier = "44444444-4444-4444-8444-444444444444";
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/config/platforms"))
      return new Response(JSON.stringify(config), { status: 200 });
    if (url.includes("/generations?"))
      return new Response(
        JSON.stringify({
          items: [
            {
              id: earlier,
              status: "completed",
              stage: "completed",
              progress: 100,
              input_type: "image",
              platform: "youtube",
              format: "thumbnail",
              output_kind: "image",
              headline: "Desk tour",
              created_at: "2026-11-18T10:00:00Z",
            },
          ],
        }),
        { status: 200 },
      );
    return new Response(JSON.stringify({ ...job, id: earlier }), {
      status: 200,
    });
  });
  render(<Home />);
  const list = await screen.findByRole("list", { name: "Recent creatives" });
  const link = within(list).getByRole("link", { name: /Desk tour/ });
  expect(link).toHaveTextContent("YouTube Thumbnail");
  fireEvent.click(link);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(
    await screen.findByText(`Generation ${earlier}`, {}, { timeout: 4000 }),
  ).toBeInTheDocument();
  expect(link).toHaveAttribute("aria-current", "page");
});

it("explains and stops polling when a job link is not available in this browser", async () => {
  const foreign = "33333333-3333-4333-8333-333333333333";
  window.history.replaceState(null, "", `#job=${foreign}`);
  const fetch = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/config/platforms"))
        return new Response(JSON.stringify(config), { status: 200 });
      return new Response(JSON.stringify({ detail: "Generation not found." }), {
        status: 404,
      });
    });
  render(<Home />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "only in the browser that created",
  );
  expect(screen.queryByText(/Reconnecting/)).not.toBeInTheDocument();
  await new Promise((resolve) => setTimeout(resolve, 3000));
  const jobCalls = fetch.mock.calls.filter(([input]) =>
    String(input).includes(foreign),
  );
  expect(jobCalls).toHaveLength(1);
  window.history.replaceState(null, "", "/");
}, 8000);

describe("background music", () => {
  it("is offered for video formats, validated, and sent with the request", async () => {
    window.history.replaceState(null, "", "/");
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:sample");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const fetch = mockFetch({ ...job, status: "queued", stage: "validating" });
    render(<Home />);
    await screen.findByText("Demo mode is on.");
    const music = screen.getByLabelText(/Background music/);
    fireEvent.change(music, {
      target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose an MP3, M4A, or WAV track.",
    );
    const huge = new File(["x"], "long.mp3", { type: "audio/mpeg" });
    Object.defineProperty(huge, "size", { value: 21 * 1024 * 1024 });
    fireEvent.change(music, { target: { files: [huge] } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose a music track smaller than 20 MB.",
    );
    const track = new File(["x"], "track.mp3", { type: "audio/mpeg" });
    fireEvent.change(music, { target: { files: [track] } });
    expect(screen.getByText("track.mp3")).toBeInTheDocument();
    expect(screen.getByText(/With your music/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Product image"), {
      target: {
        files: [new File(["test"], "product.png", { type: "image/png" })],
      },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Create my Instagram Reel/ }),
    );
    await screen.findByText("Your request is in the queue.");
    const call = fetch.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/generations") && init?.method === "POST",
    );
    expect((call?.[1]?.body as FormData).get("music")).toBe(track);
  });

  it("is hidden and not sent for image formats", async () => {
    window.history.replaceState(null, "", "/");
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:sample");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const fetch = mockFetch({ ...job, status: "queued", stage: "validating" });
    render(<Home />);
    await screen.findByText("Demo mode is on.");
    fireEvent.change(screen.getByLabelText(/Background music/), {
      target: {
        files: [new File(["x"], "track.mp3", { type: "audio/mpeg" })],
      },
    });
    fireEvent.change(screen.getByLabelText("Format"), {
      target: { value: "feed_square" },
    });
    expect(screen.queryByLabelText(/Background music/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Product image"), {
      target: {
        files: [new File(["test"], "product.png", { type: "image/png" })],
      },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Create my Instagram Square/ }),
    );
    await screen.findByText("Your request is in the queue.");
    const call = fetch.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/generations") && init?.method === "POST",
    );
    expect((call?.[1]?.body as FormData).get("music")).toBeNull();
  });
});

describe("brand kit", () => {
  async function startWithImage() {
    window.history.replaceState(null, "", "/");
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:sample");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const fetch = mockFetch({ ...job, status: "queued", stage: "validating" });
    render(<Home />);
    await screen.findByText("Demo mode is on.");
    fireEvent.change(screen.getByLabelText("Product image"), {
      target: {
        files: [new File(["x"], "product.png", { type: "image/png" })],
      },
    });
    return fetch;
  }
  async function submitted(fetch: ReturnType<typeof mockFetch>) {
    fireEvent.click(
      screen.getByRole("button", { name: /Create my Instagram Reel/ }),
    );
    await screen.findByText("Your request is in the queue.");
    const call = fetch.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/generations") && init?.method === "POST",
    );
    return call?.[1]?.body as FormData;
  }

  it("sends the chosen brand colour and logo", async () => {
    const fetch = await startWithImage();
    fireEvent.change(screen.getByLabelText("Brand colour"), {
      target: { value: "#e4572e" },
    });
    expect(screen.getByText("#E4572E")).toBeInTheDocument();
    const logo = new File(["x"], "logo.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/^Logo/), {
      target: { files: [logo] },
    });
    expect(screen.getByText("logo.png")).toBeInTheDocument();
    const data = await submitted(fetch);
    expect(data.get("brand_color")).toBe("#E4572E");
    expect(data.get("logo")).toBe(logo);
  });

  it("validates the logo before upload", async () => {
    await startWithImage();
    const field = screen.getByLabelText(/^Logo/);
    fireEvent.change(field, {
      target: { files: [new File(["x"], "logo.gif", { type: "image/gif" })] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose a PNG, JPEG, or WebP logo.",
    );
    const huge = new File(["x"], "logo.png", { type: "image/png" });
    Object.defineProperty(huge, "size", { value: 3 * 1024 * 1024 });
    fireEvent.change(field, { target: { files: [huge] } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose a logo smaller than 2 MB.",
    );
  });

  it("sends neither when they are not chosen or are removed", async () => {
    const fetch = await startWithImage();
    expect(
      screen.getByText("From your product photo"),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Brand colour"), {
      target: { value: "#1a237e" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove brand colour" }));
    fireEvent.change(screen.getByLabelText(/^Logo/), {
      target: {
        files: [new File(["x"], "logo.png", { type: "image/png" })],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove logo" }));
    const data = await submitted(fetch);
    expect(data.get("brand_color")).toBeNull();
    expect(data.get("logo")).toBeNull();
  });
});
