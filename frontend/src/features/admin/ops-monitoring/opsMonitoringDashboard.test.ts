import { describe, expect, it } from "vitest";

import { adminRoutes } from "@/config/routes";
import { adminMenuItems } from "@/config/menu";
import { OPS_DASHBOARD_LABELS } from "@/features/admin/ops-monitoring/opsMonitoringLabels";

function flattenMenu(
  items: typeof adminMenuItems,
): { key: string; path?: string; label?: string }[] {
  const out: { key: string; path?: string; label?: string }[] = [];
  for (const item of items) {
    out.push({
      key: item.key,
      path: item.path,
      label: String(item.label ?? ""),
    });
    if (item.children?.length) {
      out.push(...flattenMenu(item.children as typeof adminMenuItems));
    }
  }
  return out;
}

describe("STEP 8-11A operations dashboard labels", () => {
  it("exposes admin operations-dashboard route", () => {
    expect(adminRoutes.operationsDashboard).toBe(
      "/admin/operations-dashboard",
    );
  });

  it("shows Korean menu label", () => {
    const hub = flattenMenu(adminMenuItems).find(
      (item) => item.key === "autotrading-upbit",
    );
    const raw = adminMenuItems
      .find((item) => item.key === "autotrading")
      ?.children?.find((item) => item.key === "autotrading-upbit");
    expect(hub?.label).toBe("업비트");
    expect(raw?.matchPaths).toContain(adminRoutes.operationsDashboard);
    expect(OPS_DASHBOARD_LABELS.pageTitle).toContain("거래 운영 현황");
  });

  it("UTF-8 Korean tab labels are intact", () => {
    expect(OPS_DASHBOARD_LABELS.tabOverview).toBe("개요");
    expect(OPS_DASHBOARD_LABELS.tabAccounts).toBe("계좌 준비 상태");
    expect(OPS_DASHBOARD_LABELS.tabOrders).toContain("주문");
    expect(OPS_DASHBOARD_LABELS.recoveryScheduler).toBe("복구 스케줄러");
    expect(OPS_DASHBOARD_LABELS.orderableKrw).toBe("주문 가능 원화");
    expect(OPS_DASHBOARD_LABELS.pageTitle).toBe("거래 운영 현황");
  });
});
