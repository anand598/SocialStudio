// Shared browser-side API access. Same-origin /api by default (proxied by Next.js).
export const API = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    // The job-owner cookie must also reach a separately hosted API (NEXT_PUBLIC_API_URL).
    credentials: "include",
    signal: AbortSignal.timeout(30000),
  });
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(errorMessage(data?.detail), response.status);
  return data as T;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

type ValidationIssue = { loc?: (string | number)[]; msg?: string };

// FastAPI returns a string for handled errors and a list for request validation errors.
function errorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const issues = (detail as ValidationIssue[])
      .slice(0, 3)
      .map((issue) => {
        const field = issue.loc?.filter((part) => part !== "body").join(".");
        return field ? `${field} — ${issue.msg}` : issue.msg;
      })
      .filter(Boolean);
    if (issues.length)
      return `The server rejected the request: ${issues.join("; ")}.`;
  }
  return "The request could not be completed. Check the input and try again.";
}
