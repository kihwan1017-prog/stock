import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["antd", "@ant-design/icons", "@ant-design/cssinjs"],
  // localhost와 127.0.0.1 혼용 시 HMR 차단 해제
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
