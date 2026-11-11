import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  async redirects() {
    return [{ source: "/chat", destination: "/", permanent: false }];
  },
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "same-origin" },
    ] }];
  },
};
export default config;
