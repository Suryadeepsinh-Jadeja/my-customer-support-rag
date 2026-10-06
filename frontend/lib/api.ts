// Browser-side API client. All calls go to this app's own /api/* route, which forwards
// them to the FastAPI backend, so auth cookies stay first-party and httpOnly.

import type { ApiErrorBody } from "@/types/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: { field: string; issue: string }[] = [],
  ) {
    super(message);
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${name}=`))
    ?.slice(name.length + 1);
}

export async function api<T>(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) {
    const csrf = readCookie("csrf_token");
    if (csrf) headers["X-CSRF-Token"] = decodeURIComponent(csrf);
  }

  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: "same-origin",
      signal: init.signal,
    });
  } catch {
    throw new ApiError(0, "network_error", "We couldn't reach the server. Check your connection.");
  }

  if (response.status === 204) return undefined as T;

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (data as ApiErrorBody | null)?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? "Something went wrong. Please try again.",
      error?.fields ?? [],
    );
  }
  return data as T;
}
