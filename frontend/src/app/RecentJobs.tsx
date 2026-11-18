"use client";

import { useEffect, useState } from "react";
import { API, request } from "../lib/api";

type Summary = {
  id: string;
  status: "queued" | "processing" | "completed" | "failed";
  platform: string;
  format: string;
  output_kind: "video" | "image";
  headline: string | null;
  // 1 for originals; 2+ for "another version" jobs (absent from older APIs).
  variant?: number;
};

const HISTORY_LIMIT = 12;

const statusLabel: Record<Summary["status"], string> = {
  queued: "In progress",
  processing: "In progress",
  completed: "Ready",
  failed: "Failed",
};

/**
 * The creatives this browser has made (the API scopes the list to the owner cookie).
 * History is a convenience: if it is empty or cannot load, the section stays out of the way.
 */
export default function RecentJobs({
  activeId,
  refreshKey,
  labelFor,
}: {
  activeId: string;
  // Changes whenever the open job is created or changes state, so the list stays current.
  refreshKey: string;
  labelFor: (platform: string, format: string) => string;
}) {
  const [items, setItems] = useState<Summary[]>([]);

  useEffect(() => {
    let cancelled = false;
    request<{ items: Summary[] }>(`/api/v1/generations?limit=${HISTORY_LIMIT}`)
      .then((data) => {
        if (!cancelled) setItems(Array.isArray(data?.items) ? data.items : []);
      })
      .catch(() => {
        // Keep whatever was shown before; history must never block creating.
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (!items.length) return null;
  return (
    <section className="recent-panel panel" aria-labelledby="recent-heading">
      <div className="panel-heading">
        <h2 id="recent-heading">Recent creatives</h2>
        <span className="small-label">THIS BROWSER</span>
      </div>
      <ul className="recent-list" aria-label="Recent creatives">
        {items.map((item) => {
          const label = labelFor(item.platform, item.format);
          return (
            <li key={item.id}>
              <a
                className="recent-card"
                href={`#job=${item.id}`}
                aria-current={item.id === activeId ? "page" : undefined}
              >
                <span className="recent-thumb">
                  {item.status === "completed" ? (
                    <img
                      src={`${API}/api/v1/generations/${item.id}/thumbnail`}
                      alt=""
                      loading="lazy"
                    />
                  ) : (
                    <span className={`recent-status ${item.status}`}>
                      {statusLabel[item.status]}
                    </span>
                  )}
                </span>
                <span className="recent-text">
                  {item.headline && (
                    <strong className="recent-headline">{item.headline}</strong>
                  )}
                  <span className="recent-format">
                    {label}
                    {(item.variant ?? 1) > 1 && (
                      <span className="recent-variant">
                        <span aria-hidden="true">v{item.variant}</span>
                        <span className="sr-only">, Version {item.variant}</span>
                      </span>
                    )}
                  </span>
                </span>
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
