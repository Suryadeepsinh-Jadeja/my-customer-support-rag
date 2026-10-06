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

function toApiError(status: number, data: unknown): ApiError {
  const error = (data as ApiErrorBody | null)?.error;
  return new ApiError(
    status,
    error?.code ?? "http_error",
    error?.message ?? "Something went wrong. Please try again.",
    error?.fields ?? [],
  );
}

/**
 * Upload a file as multipart/form-data, reporting progress (0-100).
 * Uses XMLHttpRequest because fetch() has no upload progress events.
 */
export function uploadFile<T>(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    const csrf = readCookie("csrf_token");
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", decodeURIComponent(csrf));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        // non-JSON error page, handled below
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(toApiError(xhr.status, data));
    };
    xhr.onerror = () =>
      reject(new ApiError(0, "network_error", "The upload failed. Check your connection."));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export async function api<T>(
  path: string,
  init: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    headers?: Record<string, string>;
  } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...init.headers };
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
  if (!response.ok) throw toApiError(response.status, data);
  return data as T;
}
