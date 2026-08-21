import { describe, expect, it } from "vitest";

import { NOTIFICATION_EVENT_CATALOG } from "./opsCatalog";

describe("notification korean template admin surface", () => {
  it("keeps ops catalog non-empty for admin list", () => {
    expect(NOTIFICATION_EVENT_CATALOG.length).toBeGreaterThan(5);
    expect(
      NOTIFICATION_EVENT_CATALOG.some((row) => row.id.includes("ORDER")),
    ).toBe(true);
  });
});
