import type { NextConfig } from "next";

const backend = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
