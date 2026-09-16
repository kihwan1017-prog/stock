import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";

import {
  ADMIN_SR_READ_AFTER_USER,
  ADMIN_SR_READ_PREFIX,
  ADMIN_SR_READ_SUFFIX,
  STRATEGY_REQUEST_READ_COLUMN_KEYS,
  USER_SR_READ_COLUMN_ORDER,
  buildStrategyRequestReadColumns,
} from "@/shared/strategyRequests/strategyRequestReadColumns";

const srcRoot = join(process.cwd(), "src");

function walk(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === ".next") continue;
      walk(full, out);
    } else if (name.endsWith(".ts") || name.endsWith(".tsx")) {
      out.push(full);
    }
  }
  return out;
}

describe("M6-C Strategy Request READ columns", () => {
  it("shared COMMON_READ key count = 4 (M6-C0 SoT)", () => {
    expect(STRATEGY_REQUEST_READ_COLUMN_KEYS).toHaveLength(4);
    expect([...STRATEGY_REQUEST_READ_COLUMN_KEYS]).toEqual([
      "strategy_request_id",
      "candidate_id",
      "status",
      "requested_at",
    ]);
  });

  it("buildStrategyRequestReadColumns returns matching dataIndex list", () => {
    const cols = buildStrategyRequestReadColumns(STRATEGY_REQUEST_READ_COLUMN_KEYS);
    expect(cols).toHaveLength(4);
    expect(cols.map((c) => (c as { dataIndex?: string }).dataIndex)).toEqual([
      ...STRATEGY_REQUEST_READ_COLUMN_KEYS,
    ]);
  });

  it("Admin segments preserve UX order slots around Admin-only columns", () => {
    expect([
      ...ADMIN_SR_READ_PREFIX,
      ...ADMIN_SR_READ_AFTER_USER,
      ...ADMIN_SR_READ_SUFFIX,
    ]).toEqual([...STRATEGY_REQUEST_READ_COLUMN_KEYS]);
    expect(USER_SR_READ_COLUMN_ORDER).toEqual([
      ...STRATEGY_REQUEST_READ_COLUMN_KEYS,
    ]);
  });

  it("shared columns have no mutation / API / permission / history strings", () => {
    const src = readFileSync(
      join(srcRoot, "shared/strategyRequests/strategyRequestReadColumns.tsx"),
      "utf8",
    );
    for (const banned of [
      "approveStrategyRequest(",
      "rejectStrategyRequest(",
      "createStrategyRequest(",
      "cancelStrategyRequest(",
      "adminApi",
      "userApi",
      "useMutation",
      "useQuery",
      "PermissionButton",
      "require_admin",
      'dataIndex: "user_id"',
      "candidate_lifecycle_status_snapshot",
      "getStrategyRequestHistory",
      "history_id",
      "reviewer_user_id",
    ]) {
      expect(src).not.toContain(banned);
    }
  });

  it("reuses STRATEGY_REQUEST_STATUS_COLOR from M6-A", () => {
    const src = readFileSync(
      join(srcRoot, "shared/strategyRequests/strategyRequestReadColumns.tsx"),
      "utf8",
    );
    expect(src).toContain("STRATEGY_REQUEST_STATUS_COLOR");
    expect(src).toContain("@/shared/utils/strategyStatusColors");
    expect(src).not.toMatch(/PENDING_REVIEW:\s*["']processing["']/);
  });
});

describe("M6-C wire + import direction", () => {
  const adminPage = () =>
    readFileSync(
      join(srcRoot, "app/(admin)/admin/strategy-requests/page.tsx"),
      "utf8",
    );
  const userPage = () =>
    readFileSync(
      join(srcRoot, "app/(user)/user/strategy-requests/page.tsx"),
      "utf8",
    );

  it("Admin/User import shared strategyRequestReadColumns", () => {
    expect(adminPage()).toContain(
      "@/shared/strategyRequests/strategyRequestReadColumns",
    );
    expect(userPage()).toContain(
      "@/shared/strategyRequests/strategyRequestReadColumns",
    );
  });

  it("Admin keeps user_id and lifecycle snapshot columns", () => {
    const src = adminPage();
    expect(src).toContain('dataIndex: "user_id"');
    expect(src).toContain('dataIndex: "candidate_lifecycle_status_snapshot"');
  });

  it("Admin approve/reject stay outside shared columns", () => {
    const src = adminPage();
    expect(src).toContain("approveMutation");
    expect(src).toContain("rejectMutation");
    expect(src).toContain("승인");
    expect(src).toContain("반려");
  });

  it("User create/cancel stay outside shared columns", () => {
    const src = userPage();
    expect(src).toContain("createMutation");
    expect(src).toContain("cancelMutation");
    expect(src).toContain("전략 요청");
    expect(src).toContain("요청 취소");
  });

  it("user → admin/utils import remains 0", () => {
    const hits: string[] = [];
    for (const file of [
      ...walk(join(srcRoot, "features", "user")),
      ...walk(join(srcRoot, "app", "(user)")),
    ]) {
      const text = readFileSync(file, "utf8");
      if (text.includes("@/features/admin/utils/dataHelpers")) {
        hits.push(file.replace(/\\/g, "/"));
      }
    }
    expect(hits).toEqual([]);
  });

  it("admin strategy-requests does not import features/user", () => {
    expect(adminPage()).not.toMatch(/@\/features\/user\//);
  });

  it("user strategy-requests does not import features/admin", () => {
    expect(userPage()).not.toMatch(/@\/features\/admin\//);
  });
});
