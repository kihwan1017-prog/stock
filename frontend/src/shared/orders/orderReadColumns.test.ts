import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";

import {
  ADMIN_ORDER_READ_PREFIX,
  ADMIN_ORDER_READ_SUFFIX,
  ORDER_READ_COLUMN_KEYS,
  USER_ORDER_READ_COLUMN_ORDER,
  buildOrderReadColumns,
  createOrderReadColumn,
  replaceOrderReadColumn,
} from "@/shared/orders/orderReadColumns";

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

describe("M6-B order READ columns", () => {
  it("shared COMMON_READ key count = 7 (M6-B0 SoT)", () => {
    expect(ORDER_READ_COLUMN_KEYS).toHaveLength(7);
    expect([...ORDER_READ_COLUMN_KEYS]).toEqual([
      "order_id",
      "exchange_code",
      "symbol",
      "side_code",
      "status_code",
      "order_quantity",
      "order_price",
    ]);
  });

  it("buildOrderReadColumns returns matching dataIndex list", () => {
    const cols = buildOrderReadColumns(ORDER_READ_COLUMN_KEYS);
    expect(cols).toHaveLength(7);
    expect(cols.map((c) => (c as { dataIndex?: string }).dataIndex)).toEqual([
      ...ORDER_READ_COLUMN_KEYS,
    ]);
  });

  it("shared columns have no permission / mutation / owner filter strings", () => {
    const src = readFileSync(
      join(srcRoot, "shared/orders/orderReadColumns.ts"),
      "utf8",
    );
    for (const banned of [
      "user_id",
      "PermissionButton",
      "trading:write",
      "cancelTrading",
      "resolveNotSubmitted",
      "retireUnsubmitted",
      "adminApi",
      "userApi",
      "useMutation",
      "useQuery",
    ]) {
      expect(src).not.toContain(banned);
    }
  });

  it("replaceOrderReadColumn swaps status only", () => {
    const base = buildOrderReadColumns(USER_ORDER_READ_COLUMN_ORDER);
    const rich = createOrderReadColumn("status_code", {
      title: "상태",
      width: 220,
    });
    const next = replaceOrderReadColumn(base, "status_code", {
      ...rich,
      render: () => "RICH",
    });
    const status = next.find(
      (c) => (c as { dataIndex?: string }).dataIndex === "status_code",
    );
    expect(status?.render?.(undefined, {} as never, 0)).toBe("RICH");
    expect(next).toHaveLength(7);
  });

  it("Admin prefix+suffix covers 7 keys without broker", () => {
    expect([...ADMIN_ORDER_READ_PREFIX, ...ADMIN_ORDER_READ_SUFFIX]).toEqual([
      ...ORDER_READ_COLUMN_KEYS,
    ]);
  });
});

describe("M6-B wire + import direction", () => {
  const adminOrders = () =>
    readFileSync(
      join(srcRoot, "app/(admin)/admin/orders/page.tsx"),
      "utf8",
    );
  const userOrders = () =>
    readFileSync(join(srcRoot, "app/(user)/user/orders/page.tsx"), "utf8");
  const broker = () =>
    readFileSync(
      join(srcRoot, "features/user/orders/BrokerOrdersView.tsx"),
      "utf8",
    );

  it("Admin/User/BrokerOrdersView import shared orderReadColumns", () => {
    expect(adminOrders()).toContain("@/shared/orders/orderReadColumns");
    expect(userOrders()).toContain("@/shared/orders/orderReadColumns");
    expect(broker()).toContain("@/shared/orders/orderReadColumns");
  });

  it("Admin keeps broker_code and action columns", () => {
    const src = adminOrders();
    expect(src).toContain('dataIndex: "broker_code"');
    expect(src).toContain("취소");
    expect(src).toContain("미전송");
    expect(src).toContain("보기");
    expect(src).toContain("PermissionButton");
  });

  it("User keeps created_at and BrokerOrdersView rich status", () => {
    expect(userOrders()).toContain('dataIndex: "created_at"');
    expect(broker()).toContain("AMBIGUOUS_SUBMISSION");
    expect(broker()).toContain("다음 재조회");
    expect(broker()).toContain("replaceOrderReadColumn");
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

  it("admin does not import features/user for order columns", () => {
    expect(adminOrders()).not.toMatch(/@\/features\/user\//);
  });
});
