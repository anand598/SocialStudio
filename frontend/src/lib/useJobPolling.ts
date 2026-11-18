"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, request } from "./api";
import type { Job } from "./types";

const POLL_INTERVAL_MS = 2500;

/**
 * The job open in the studio: follows the shareable `#job=` link, polls it until it
 * finishes, and flags links this browser cannot open (the API answers 404 for missing
 * jobs and for jobs created in another browser alike).
 */
export function useJobPolling() {
  const [job, setJob] = useState<Job | null>(null);
  const [jobID, setJobID] = useState("");
  const [pollError, setPollError] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  // Read by async callbacks that must not act on a job the user has since left.
  const openJobID = useRef("");

  useEffect(() => {
    openJobID.current = jobID;
  }, [jobID]);
  useEffect(() => {
    // The #job= fragment is the shareable result link; follow it on load and on
    // back/forward or pasted-link navigation, which change the hash without a reload.
    const restore = () => {
      const id = new URLSearchParams(window.location.hash.slice(1)).get("job");
      if (id && /^[0-9a-f-]{36}$/i.test(id)) {
        setJobID(id);
      } else {
        // No job in the URL (e.g. Back to the start page): show the empty studio.
        setJobID("");
        setJob(null);
      }
    };
    restore();
    window.addEventListener("hashchange", restore);
    return () => window.removeEventListener("hashchange", restore);
  }, []);
  useEffect(() => {
    setUnavailable(false);
    if (!jobID) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<Job>(`/api/v1/generations/${jobID}`);
        if (cancelled) return;
        setJob(next);
        setPollError("");
        if (next.status === "completed" || next.status === "failed") return;
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setJob(null);
          setPollError("");
          setUnavailable(true);
          return;
        }
        setPollError(
          err instanceof Error
            ? err.message
            : "Connection interrupted. Reconnecting…",
        );
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobID]);

  // Open a job the API just returned and poll it until it finishes.
  const open = useCallback((next: Job) => {
    setJob(next);
    setJobID(next.id);
  }, []);
  // Like open, but restarts polling even when it is the job already open (a retry).
  const reopen = useCallback((next: Job) => {
    setJob(next);
    setJobID("");
    setTimeout(() => setJobID(next.id), 0);
  }, []);
  const isOpen = useCallback((id: string) => openJobID.current === id, []);

  return { job, jobID, pollError, unavailable, open, reopen, isOpen };
}
