import { z } from "zod";

const envSchema = z.object({
  NEXT_PUBLIC_APP_NAME: z.string().min(1),
  // 빈 문자열 / same-origin → 브라우저 same-origin (Next rewrite → backend)
  NEXT_PUBLIC_API_BASE_URL: z.string().default(""),
  NEXT_PUBLIC_API_PREFIX: z.string().startsWith("/"),
  NEXT_PUBLIC_WS_BASE_URL: z.string().min(1),
  NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS: z
    .enum(["true", "false"])
    .transform((value) => value === "true"),
  // JWT 백엔드 인증만 지원 (개발 우회 모드 제거)
  NEXT_PUBLIC_AUTH_MODE: z.enum(["backend"]).default("backend"),
});

const parsed = envSchema.safeParse({
  NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "",
  NEXT_PUBLIC_API_PREFIX: process.env.NEXT_PUBLIC_API_PREFIX,
  NEXT_PUBLIC_WS_BASE_URL: process.env.NEXT_PUBLIC_WS_BASE_URL,
  NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS:
    process.env.NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS,
  NEXT_PUBLIC_AUTH_MODE: process.env.NEXT_PUBLIC_AUTH_MODE ?? "backend",
});

if (!parsed.success) {
  const details = parsed.error.issues
    .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
    .join("\n");
  throw new Error(`Invalid environment variables:\n${details}`);
}

function resolveApiBaseUrl(raw: string): string {
  const value = raw.trim().replace(/\/$/, "");
  if (!value || value === "same-origin" || value === "/") {
    return "";
  }
  // 실수로 URL이 아니면 개발 중 즉시 실패
  try {
    // eslint-disable-next-line no-new
    new URL(value);
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL must be absolute URL or empty/same-origin: ${value}`,
    );
  }
  return value;
}

export const env = {
  APP_NAME: parsed.data.NEXT_PUBLIC_APP_NAME,
  API_BASE_URL: resolveApiBaseUrl(parsed.data.NEXT_PUBLIC_API_BASE_URL),
  API_PREFIX: parsed.data.NEXT_PUBLIC_API_PREFIX,
  WS_BASE_URL: parsed.data.NEXT_PUBLIC_WS_BASE_URL,
  ENABLE_REACT_QUERY_DEVTOOLS: parsed.data.NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS,
  AUTH_MODE: parsed.data.NEXT_PUBLIC_AUTH_MODE,
} as const;

export type AuthMode = (typeof env)["AUTH_MODE"];
