import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const host = request.headers.get("host") ?? "";
  const pathname = request.nextUrl.pathname;

  // Skip static files and API routes
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // cortex.oni.bot → /cortex routes
  if (host.startsWith("cortex.")) {
    if (!pathname.startsWith("/cortex")) {
      const url = request.nextUrl.clone();
      url.pathname = `/cortex${pathname}`;
      return NextResponse.rewrite(url);
    }
  }

  // oni.bot → /brand routes
  if (!pathname.startsWith("/brand") && !pathname.startsWith("/cortex")) {
    const url = request.nextUrl.clone();
    url.pathname = `/brand${pathname}`;
    return NextResponse.rewrite(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
