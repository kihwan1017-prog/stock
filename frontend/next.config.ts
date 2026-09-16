import type { NextConfig } from "next";

/** 브라우저→같은 origin. 서버만 loopback backend로 proxy (휴대폰 LAN용). */
const BACKEND_ORIGIN =
  process.env.STOCK_PLATFORM_BACKEND_ORIGIN?.trim() ||
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  transpilePackages: ["antd", "@ant-design/icons", "@ant-design/cssinjs"],
  // localhost·LAN·Tailscale MagicDNS 혼용 시 HMR/dev origin 허용
  // 미허용 시 폰에서 /_next/webpack-hmr 403 → 전체 리로드 루프(세션 확인 중 반복)
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    "192.168.1.2",
    "100.79.126.15",
    "stock.tail3bf7b2.ts.net",
    "kikicom.tail3bf7b2.ts.net",
    "lottolab.tail3bf7b2.ts.net",
    "*.tail3bf7b2.ts.net",
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
