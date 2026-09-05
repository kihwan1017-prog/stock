import type { MetadataRoute } from "next";

/** Single installable PWA — mobile shell at /mobile (legacy start_url 호환). */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "KIKI AI Trading",
    short_name: "KIKI",
    description: "KIKI AI 자동매매 상태 · 모바일 PWA",
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
