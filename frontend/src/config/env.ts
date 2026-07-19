import { z } from "zod";

const envSchema = z.object({
  NEXT_PUBLIC_APP_NAME: z.string().min(1),
  NEXT_PUBLIC_API_BASE_URL: z.string().url(),
  NEXT_PUBLIC_API_PREFIX: z.string().startsWith("/"),
  NEXT_PUBLIC_WS_BASE_URL: z.string().min(1),
  NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS: z
    .enum(["true", "false"])
    .transform((value) => value === "true"),
  NEXT_PUBLIC_AUTH_MODE: z.enum(["backend", "disabled"]),
});

const parsed = envSchema.safeParse({
  NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME,
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  NEXT_PUBLIC_API_PREFIX: process.env.NEXT_PUBLIC_API_PREFIX,
  NEXT_PUBLIC_WS_BASE_URL: process.env.NEXT_PUBLIC_WS_BASE_URL,
  NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS:
    process.env.NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS,
  NEXT_PUBLIC_AUTH_MODE: process.env.NEXT_PUBLIC_AUTH_MODE,
});

if (!parsed.success) {
  const details = parsed.error.issues
    .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
    .join("\n");
  throw new Error(`Invalid environment variables:\n${details}`);
}

export const env = {
  APP_NAME: parsed.data.NEXT_PUBLIC_APP_NAME,
  API_BASE_URL: parsed.data.NEXT_PUBLIC_API_BASE_URL,
  API_PREFIX: parsed.data.NEXT_PUBLIC_API_PREFIX,
  WS_BASE_URL: parsed.data.NEXT_PUBLIC_WS_BASE_URL,
  ENABLE_REACT_QUERY_DEVTOOLS: parsed.data.NEXT_PUBLIC_ENABLE_REACT_QUERY_DEVTOOLS,
  AUTH_MODE: parsed.data.NEXT_PUBLIC_AUTH_MODE,
} as const;

export type AuthMode = (typeof env)["AUTH_MODE"];
