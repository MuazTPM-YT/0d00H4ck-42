import { type NextRequest, NextResponse } from "next/server";

// no auth cookie -> login page. Only a convenience: the API checks the token on every call.
export function middleware(req: NextRequest) {
  if (req.cookies.has("access_token")) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!login|track|deliver|api|_next|favicon.ico).*)"],
};
