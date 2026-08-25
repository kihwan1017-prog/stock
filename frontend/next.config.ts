import type { NextConfig } from "next";

/** 브라우저→같은 origin. 서버만 loopback backend로 proxy (휴대폰 LAN용). */
const BACKEND_ORIGIN =
  process.env.STOCK_PLATFORM_BACKEND_ORIGIN?.trim() ||
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  transpilePackages: ["antd", "@ant-design/icons", "@ant-design/cssinjs"],
  // localhost·LAN IP 혼용 시 HMR/dev origin 허용
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    "192.168.1.2",
  ],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${BACKEND_ORIGIN}/health`,
      },
      {
        source: "/health/:path*",
        destination: `${BACKEND_ORIGIN}/health/:path*`,
      },
      {
        source: "/version",
        destination: `${BACKEND_ORIGIN}/version`,
      },
    ];
  },
};

export default nextConfig;
