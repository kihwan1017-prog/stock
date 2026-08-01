import { describe, expect, it } from "vitest";

import { adminRoutes, userRoutes } from "@/config/routes";
import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { ADMIN_MANUAL_SECTIONS } from "@/features/manual/manualDataAdmin";
import { USER_MANUAL_SECTIONS } from "@/features/manual/manualDataUser";
import { AUTO_TRADING_MARKET_FLOWS } from "@/features/manual/manualDataTrading";
import { SAFETY_IMMEDIATE_STOP_CONDITIONS } from "@/features/manual/manualDataSafety";
import { MANUAL_STATUS_LABEL } from "@/features/manual/manualTypes";

const SECRET_PATTERNS = [
  /api[_-]?key\s*[:=]\s*['\"]?[a-z0-9_-]{8,}/i,
  /secret\s*[:=]\s*['\"]?[a-z0-9_-]{8,}/i,
  /Bearer\s+[A-Za-z0-9\-._~+/]+=*/,
  /ACCESS_KEY\s*=\s*\S+/i,
];

function collectText(): string {
  const chunks: string[] = [];
  for (const section of [...USER_MANUAL_SECTIONS, ...ADMIN_MANUAL_SECTIONS]) {
    chunks.push(
      section.title,
      section.purpose,
      section.liveImpact,
      ...(section.steps ?? []),
      ...(section.notes ?? []),
      ...(section.errors ?? []),
    );
  }
  for (const flow of AUTO_TRADING_MARKET_FLOWS) {
    chunks.push(flow.title, ...flow.steps, ...flow.warnings);
  }
  chunks.push(...SAFETY_IMMEDIATE_STOP_CONDITIONS);
  return chunks.join("\n");
}

describe("admin integrated manual", () => {
  it("메뉴에 매뉴얼 경로가 있다", () => {
    const flat = flattenMenuItems(adminMenuItems);
    const manual = flat.find((item) => item.path === adminRoutes.docsManual);
    expect(manual?.label).toBe("매뉴얼");
    expect(manual?.permission).toBe("menu:docs");
  });

  it("문서관리 그룹 아래 문서 CMS와 매뉴얼이 있다", () => {
    const docsGroup = adminMenuItems
      .find((item) => item.key === "system")
      ?.children?.find((item) => item.key === "documents-group");
    expect(docsGroup?.label).toBe("문서관리");
    const labels = docsGroup?.children?.map((c) => c.label) ?? [];
    expect(labels).toEqual(expect.arrayContaining(["문서 CMS", "매뉴얼"]));
  });

  it("사용자/관리자 섹션 route가 실제 routes에 존재한다", () => {
    const known = new Set<string>([
      ...Object.values(userRoutes),
      ...Object.values(adminRoutes),
    ]);
    for (const section of [...USER_MANUAL_SECTIONS, ...ADMIN_MANUAL_SECTIONS]) {
      if (section.route) {
        expect(known.has(section.route)).toBe(true);
      }
    }
  });

  it("상태 Badge 라벨이 정의되어 있다", () => {
    expect(MANUAL_STATUS_LABEL.available).toBe("사용 가능");
    expect(MANUAL_STATUS_LABEL.planned).toBe("계획됨");
    expect(MANUAL_STATUS_LABEL.default_off).toBe("기본 OFF");
  });

  it("LIVE Flag를 직접 ON 하라고 안내하지 않는다", () => {
    const text = collectText();
    expect(text).toMatch(/기본 OFF/);
    expect(text).not.toMatch(/LIVE Flag를\s*ON/);
    expect(text).not.toMatch(/LIVE_ORDER_ENABLED\s*=\s*true/i);
  });

  it("Secret 패턴이 본문에 없다", () => {
    const text = collectText();
    for (const pattern of SECRET_PATTERNS) {
      expect(text).not.toMatch(pattern);
    }
  });

  it("Backup/Restore/Log Tail은 미구현으로 표시한다", () => {
    const ops = ADMIN_MANUAL_SECTIONS.find((s) => s.id === "admin-ops-center");
    expect(ops?.notes?.join(" ")).toMatch(/미구현|계획됨/);
    expect(ops?.buttons?.join(" ")).toMatch(/Disabled/);
  });
});
