import type { NextConfig } from "next";

// Next is only the frontend. Every /api call is proxied to FastAPI, so the browser
// sees one origin: no CORS, and FastAPI's httpOnly auth cookie just works.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // SSE must stream through the proxy unbuffered
  compress: false,
  devIndicators: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
