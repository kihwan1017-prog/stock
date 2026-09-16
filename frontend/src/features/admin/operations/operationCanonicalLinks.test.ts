import { describe, expect, it } from "vitest";

import { adminRoutes } from "@/config/routes";

import { OPERATION_CANONICAL_LINKS } from "./operationCanonicalLinks";

describe("M4-A operations canonical links", () => {
  it("canonical 경로만 가리키고 중복 href가 없다", () => {
    const hrefs = OPERATION_CANONICAL_LINKS.map((item) => item.href);
    expect(hrefs).toEqual([
      adminRoutes.monitoring,
      adminRoutes.operationsDashboard,
      adminRoutes.trading,
      adminRoutes.operationsPreflight,
      adminRoutes.scheduler,
      adminRoutes.orders,
      adminRoutes.risk,
      adminRoutes.recovery,
      adminRoutes.upbit,
    ]);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("route path를 새로 만들지 않는다", () => {
    expect(adminRoutes.operations).toBe("/admin/operations");
    expect(adminRoutes.trading).toBe("/admin/trading");
    expect(adminRoutes.monitoring).toBe("/admin/monitoring");
    expect(adminRoutes.recovery).toBe("/admin/recovery");
    expect(adminRoutes.risk).toBe("/admin/risk");
    expect(adminRoutes.orders).toBe("/admin/orders");
    expect(adminRoutes.scheduler).toBe("/admin/scheduler");
    expect(adminRoutes.operationsPreflight).toBe("/admin/operations/preflight");
    expect(adminRoutes.operationsDashboard).toBe("/admin/operations-dashboard");
  });
});
