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
    const docs = flat.find((item) => item.key === "docs");
    expect(docs?.label).toBe("문서");
    expect(docs?.permission).toBe("menu:docs");
    expect(docs?.path).toBe(adminRoutes.docs);
    expect(docs?.matchPaths).toContain(adminRoutes.docsManual);
  });

  it("문서 메뉴는 고급 관리 그룹에서 문서·매뉴얼 경로를 함께 담당한다", () => {
    const advanced = adminMenuItems.find((item) => item.key === "advanced");
    expect(advanced?.label).toBe("고급 관리");
    const docs = advanced?.children?.find((item) => item.key === "docs");
    expect(docs?.label).toBe("문서");
    expect(docs?.permission).toBe("menu:docs");
    expect(docs?.matchPaths).toEqual(
      expect.arrayContaining([adminRoutes.docs, adminRoutes.docsManual]),
    );
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
