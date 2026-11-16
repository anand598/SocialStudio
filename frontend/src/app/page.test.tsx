import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import Home from "./page";

const id = "11111111-1111-4111-8111-111111111111";
const config = { formats: [{ platform: "instagram", format: "reel", label: "Instagram Reel", width: 1080, height: 1920, aspect_ratio: "9:16" }], generation_mode: "demo", max_upload_size_mb: 15 };
const job = { id, status: "completed", stage: "completed", generation_mode: "demo", error_message: null,
  product_analysis: null, generated_content: { hook: "Look closer", caption: "Demo caption", call_to_action: "Shop", hashtags: ["#Demo"], disclaimer_or_assumptions: "Demo copy; review before publishing." } };
function mockFetch(result: Omit<typeof job, "error_message"> & { error_message: string | null } = job) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = String(input);
    return new Response(JSON.stringify(url.endsWith("/config/platforms") ? config : result), { status: 200 });
  });
}

describe("creative workflow", () => {
  it("labels demo mode and validates uploads before submitting", async () => {
    mockFetch(); render(<Home />);
    expect(await screen.findByText("Demo mode is on.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create my Reel/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Product image"), { target: { files: [new File(["x"], "file.txt", { type: "text/plain" })] } });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a JPEG, PNG, or WebP image.");
  });
  it("restores a completed job with preview, download and caption after refresh", async () => {
    window.history.replaceState(null, "", `#job=${id}`);
    mockFetch(); render(<Home />);
    expect(await screen.findByRole("link", { name: /Download Reel/ })).toHaveAttribute("href", expect.stringContaining(id));
    expect(screen.getByLabelText("Generated Instagram Reel")).toHaveAttribute("src", expect.stringContaining("/preview"));
    expect(screen.getByLabelText("Caption & hashtags")).toHaveValue("Demo caption\n\nShop\n\n#Demo");
    expect(screen.getByText("Demo copy; review before publishing.")).toBeInTheDocument();
  });
  it("shows queued state and submits the chosen image and format", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:sample");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const fetch = mockFetch({ ...job, status: "queued", stage: "validating" });
    render(<Home />);
    await screen.findByText("Demo mode is on.");
    const image = new File(["test"], "product.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Product image"), { target: { files: [image] } });
    fireEvent.click(screen.getByRole("button", { name: /Create my Reel/ }));
    expect(await screen.findByText("Your image is in the queue.")).toBeInTheDocument();
    const call = fetch.mock.calls.find(([url, init]) => String(url).endsWith("/generations") && init?.method === "POST");
    const data = call?.[1]?.body as FormData;
    expect(data.get("file")).toBe(image);
    expect(data.get("platform")).toBe("instagram");
    expect(data.get("format")).toBe("reel");
  });
  it("shows a safe failure and retry action", async () => {
    window.history.replaceState(null, "", `#job=${id}`);
    mockFetch({ ...job, status: "failed", error_message: "Check the worker and retry." });
    render(<Home />);
    expect(await screen.findByText("Check the worker and retry.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Retry generation/ })).toBeEnabled();
  });
});

it("polls from queued through rendering to completion", async () => {
  window.history.replaceState(null, "", `#job=${id}`);
  let statusReads = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    let result: unknown = config;
    if (!String(input).endsWith("/config/platforms")) {
      statusReads += 1;
      result = statusReads === 1 ? { ...job, status: "queued", stage: "validating" }
        : statusReads === 2 ? { ...job, status: "processing", stage: "rendering" } : job;
    }
    return new Response(JSON.stringify(result), { status: 200 });
  });
  render(<Home />);
  expect(await screen.findByText("Your image is in the queue.")).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "Render your Reel" }, { timeout: 4000 })).toBeInTheDocument();
  expect(await screen.findByText("Your product, ready to play.", {}, { timeout: 4000 })).toBeInTheDocument();
  expect(statusReads).toBe(3);
}, 10000);
