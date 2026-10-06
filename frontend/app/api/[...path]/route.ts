// Forwards /api/* to the FastAPI backend (BACKEND_URL, read at request time).
// The browser only ever talks to this origin, so auth cookies are first-party.

import type { NextRequest } from "next/server";

const BACKEND_URL = () => process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const FORWARD_REQUEST_HEADERS = [
  "accept",
  "authorization",
  "content-type",
  "cookie",
  "idempotency-key",
  "user-agent",
  "x-csrf-token",
  "x-request-id",
];

// Hop-by-hop or re-encoded by fetch; must not be copied to the client.
const DROP_RESPONSE_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "transfer-encoding",
]);

async function forward(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await params;
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, BACKEND_URL());
  target.search = request.nextUrl.search;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Pass only the nearest client address so the backend can rate-limit per client
  // without trusting a chain the client could have forged.
  const forwardedFor = request.headers.get("x-forwarded-for")?.split(",").pop()?.trim();
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { error: { code: "service_unavailable", message: "The service is temporarily unavailable." } },
      { status: 503 },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, name) => {
    if (!DROP_RESPONSE_HEADERS.has(name) && name !== "set-cookie") {
      responseHeaders.set(name, value);
    }
  });
  for (const cookie of upstream.headers.getSetCookie()) {
    responseHeaders.append("set-cookie", cookie);
  }

  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
