import { describe, expect, it } from "vitest";

import {
  evaluatePreflightFreshness,
  isPreflightLiveOnAllowed,
  PREFLIGHT_TTL_SECONDS,
  sanitizePreflightExport,
  type RuntimePreflightResponse,
} from "@/features/admin/api/adminApi";

describe("runtime preflight API surface", () => {
  it("exposes getRuntimePreflight API", async () => {
    const mod = await import("@/features/admin/api/adminApi");
    expect(typeof mod.getRuntimePreflight).toBe("function");
  });

  it("sanitizes secrets from export payload", () => {
    const cleaned = sanitizePreflightExport({
      access_key: "AK",
      secret_key: "SK",
      arm_token: "tok",
      authorization: "Bearer x",
      ciphertext: "enc",
      traceback: "boom",
      safe: "yes",
      nested: { api_secret: "x", count: 2 },
    }) as Record<string, unknown>;
    expect(cleaned.access_key).toBeUndefined();
    expect(cleaned.secret_key).toBeUndefined();
    expect(cleaned.arm_token).toBeUndefined();
    expect(cleaned.authorization).toBeUndefined();
    expect(cleaned.ciphertext).toBeUndefined();
    expect(cleaned.traceback).toBeUndefined();
    expect(cleaned.safe).toBe("yes");
    expect((cleaned.nested as Record<string, unknown>).api_secret).toBeUndefined();
    expect((cleaned.nested as Record<string, unknown>).count).toBe(2);
  });

  it("marks STALE after TTL", () => {
    const now = Date.parse("2026-08-03T15:00:00.000Z");
    const checkedAt = new Date(
      now - (PREFLIGHT_TTL_SECONDS + 1) * 1000,
    ).toISOString();
    const out = evaluatePreflightFreshness(checkedAt, PREFLIGHT_TTL_SECONDS, now);
    expect(out.status).toBe("STALE");
    expect(out.fresh).toBe(false);
  });

  it("allows LIVE ON only when READY_FOR_LIVE and FRESH", () => {
    const now = Date.parse("2026-08-03T15:00:00.000Z");
    const freshReport: RuntimePreflightResponse = {
      overall_status: "READY_FOR_LIVE",
      estimated_ready: "NOW",
      checked_at: new Date(now - 10_000).toISOString(),
      freshness: { ttl_seconds: PREFLIGHT_TTL_SECONDS, status: "FRESH" },
      checks: [],
      warnings: [],
      blockers: [],
    };
    expect(isPreflightLiveOnAllowed(freshReport, now)).toBe(true);

    const staleReport: RuntimePreflightResponse = {
      ...freshReport,
      checked_at: new Date(now - 61_000).toISOString(),
    };
    expect(isPreflightLiveOnAllowed(staleReport, now)).toBe(false);

    const blockedReport: RuntimePreflightResponse = {
      ...freshReport,
      overall_status: "BLOCKED",
      estimated_ready: null,
    };
    expect(isPreflightLiveOnAllowed(blockedReport, now)).toBe(false);
  });
});
