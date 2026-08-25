import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Stock Platform",
    short_name: "Stock",
    description: "자동매매 상태 조회 (읽기 전용)",
    start_url: "/mobile",
    scope: "/",
    display: "standalone",
    orientation: "portrait-primary",
    background_color: "#0f1419",
    theme_color: "#0f1419",
    lang: "ko-KR",
    icons: [
      {
        src: "/favicon.ico",
        sizes: "any",
        type: "image/x-icon",
        purpose: "any",
      },
    ],
  };
}
