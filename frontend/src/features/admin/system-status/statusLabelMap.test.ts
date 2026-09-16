import { describe, expect, it } from "vitest";

import {
  KOREAN_STATUS_MAPPING_COUNT,
  mapBlocker,
  mapStatus,
  overallStatusKo,
} from "@/features/admin/system-status/statusLabelMap";

describe("statusLabelMap", () => {
  it("maps RUNNING / STALE / READY to Korean labels", () => {
    expect(mapStatus("RUNNING").labelKo).toBe("실행 중");
    expect(mapStatus("FEED_STALE").labelKo).toBe("시세 수신 지연");
    expect(mapStatus("READY").labelKo).toBe("준비 완료");
  });

  it("null-safe mapping", () => {
    expect(mapStatus(null).labelKo).toBe("확인 필요");
    expect(mapStatus(undefined).labelKo).toBe("확인 필요");
  });

  it("maps blockers to Korean", () => {
    expect(mapBlocker("ARM_EXPIRED")).toContain("만료");
    expect(mapBlocker("FEED_STALE")).toContain("지연");
  });

  it("overall status titles", () => {
    expect(overallStatusKo("UP").title).toBe("정상 운영");
    expect(overallStatusKo("DEGRADED").title).toBe("일부 확인 필요");
    expect(overallStatusKo("ERROR").title).toBe("오류");
  });

  it("exposes mapping count", () => {
    expect(KOREAN_STATUS_MAPPING_COUNT).toBeGreaterThan(20);
  });
});
