// Optimistic route protection: send visitors without a session cookie to sign-in.
// Real authorization happens in the backend on every API call.

import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/register"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = request.cookies.has("access_token");
  const isPublic = PUBLIC_PATHS.includes(pathname);

  if (!signedIn && !isPublic) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", pathname + search);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the API proxy, Next.js internals and static files.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.[a-z0-9]+$).*)"],
};
