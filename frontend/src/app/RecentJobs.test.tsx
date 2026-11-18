import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import RecentJobs from "./RecentJobs";

const done = "11111111-1111-4111-8111-111111111111";
const running = "22222222-2222-4222-8222-222222222222";
const broken = "33333333-3333-4333-8333-333333333333";
const items = [
  {
    id: done,
    status: "completed",
    stage: "completed",
    progress: 100,
    input_type: "image",
    platform: "instagram",
    format: "reel",
    output_kind: "video",
    headline: "Pour slower",
    created_at: "2026-11-18T10:00:00Z",
  },
  {
    id: running,
    status: "processing",
    stage: "rendering",
    progress: 60,
    input_type: "url",
    platform: "youtube",
    format: "thumbnail",
    output_kind: "image",
    headline: null,
    created_at: "2026-11-18T09:00:00Z",
  },
  {
    id: broken,
    status: "failed",
    stage: "failed",
    progress: 0,
    input_type: "video",
    platform: "tiktok",
    format: "video",
    output_kind: "video",
    headline: null,
    created_at: "2026-11-18T08:00:00Z",
  },
];
const labels: Record<string, string> = {
  "instagram/reel": "Instagram Reel",
  "youtube/thumbnail": "YouTube Thumbnail",
  "tiktok/video": "TikTok Video",
};
const labelFor = (platform: string, format: string) =>
  labels[`${platform}/${format}`] ?? format;

function mockHistory(body: unknown, status = 200) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(
      async () => new Response(JSON.stringify(body), { status }),
    );
}

describe("recent creatives", () => {
  it("links each past creative, newest first, by headline or format", async () => {
    const fetch = mockHistory({ items });
    render(<RecentJobs activeId="" refreshKey="" labelFor={labelFor} />);
    const list = await screen.findByRole("list", { name: "Recent creatives" });
    const links = within(list).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      `#job=${done}`,
      `#job=${running}`,
      `#job=${broken}`,
    ]);
    expect(links[0]).toHaveTextContent("Pour slower");
    expect(links[0]).toHaveTextContent("Instagram Reel");
    expect(links[1]).toHaveTextContent("YouTube Thumbnail");
    expect(String(fetch.mock.calls[0][0])).toContain("/api/v1/generations?limit=");
  });

  it("shows thumbnails for finished results and status for the rest", async () => {
    mockHistory({ items });
    render(<RecentJobs activeId="" refreshKey="" labelFor={labelFor} />);
    const links = within(
      await screen.findByRole("list", { name: "Recent creatives" }),
    ).getAllByRole("link");
    // Decorative (alt=""): the link text already names the creative.
    expect(links[0].querySelector("img")).toHaveAttribute(
      "src",
      expect.stringContaining(`/api/v1/generations/${done}/thumbnail`),
    );
    expect(links[1].querySelector("img")).toBeNull();
    expect(links[1]).toHaveTextContent("In progress");
    expect(links[2]).toHaveTextContent("Failed");
  });

  it("marks the result that is open", async () => {
    mockHistory({ items });
    render(<RecentJobs activeId={running} refreshKey="" labelFor={labelFor} />);
    const links = within(
      await screen.findByRole("list", { name: "Recent creatives" }),
    ).getAllByRole("link");
    expect(links[1]).toHaveAttribute("aria-current", "page");
    expect(links[0]).not.toHaveAttribute("aria-current");
  });

  it("stays hidden when there is no history or it cannot load", async () => {
    const fetch = mockHistory({ items: [] });
    const { unmount } = render(
      <RecentJobs activeId="" refreshKey="" labelFor={labelFor} />,
    );
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: /recent/i })).toBeNull();
    unmount();
    fetch.mockRejectedValue(new TypeError("offline"));
    render(<RecentJobs activeId="" refreshKey="" labelFor={labelFor} />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("region", { name: /recent/i })).toBeNull();
  });

  it("reloads when the open job changes state", async () => {
    const fetch = mockHistory({ items: items.slice(1) });
    const { rerender } = render(
      <RecentJobs activeId={running} refreshKey="a:processing" labelFor={labelFor} />,
    );
    await screen.findByRole("list", { name: "Recent creatives" });
    fetch.mockImplementation(
      async () => new Response(JSON.stringify({ items }), { status: 200 }),
    );
    rerender(
      <RecentJobs activeId={done} refreshKey="b:completed" labelFor={labelFor} />,
    );
    expect(await screen.findByText("Pour slower")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
