import { describe, expect, it } from "vitest";

import { parseAutoRenewPreview } from "@/features/admin/upbit/upbitAutoRenewPreview";
import {
  resolveHoldingOwner,
  shouldIncludeHoldingPositionRow,
} from "@/features/admin/portfolio/holdingsRowPolicy";
import {
  formatAmountKo,
  formatCellNumeric,
  formatDecimalKo,
  formatPriceKo,
  formatQuantityKo,
  isEffectivelyZero,
  parseDecimalSafe,
} from "@/shared/utils/numericFormatKo";
import { cell } from "@/shared/utils/dataHelpers";

describe("parseAutoRenewPreview", () => {
  it("previewQ.data undefined — crash 없이 빈 precheck", () => {
    const r = parseAutoRenewPreview(undefined);
    expect(r.preview).toEqual({});
    expect(r.precheck).toEqual({});
    expect(r.precheckBlockers).toEqual([]);
    expect(r.hasPreviewData).toBe(false);
  });

  it("previewQ.data null", () => {
    const r = parseAutoRenewPreview(null);
    expect(r.preview).toEqual({});
    expect(r.hasPreviewData).toBe(false);
  });

  it("preview = {}", () => {
    const r = parseAutoRenewPreview({});
    expect(r.preview).toEqual({});
    expect(r.precheckBlockers).toEqual([]);
    expect(r.hasPreviewData).toBe(true);
  });

  it("precheck null", () => {
    const r = parseAutoRenewPreview({ precheck: null, would_renew: false });
    expect(r.precheck).toEqual({});
    expect(r.precheckBlockers).toEqual([]);
  });

  it("blockers absent", () => {
    const r = parseAutoRenewPreview({ precheck: {} });
    expect(r.precheckBlockers).toEqual([]);
  });

  it("blockers array", () => {
    const r = parseAutoRenewPreview({
      precheck: { blockers: ["KILL_SWITCH", "ARM_OFF"] },
    });
    expect(r.precheckBlockers).toEqual(["KILL_SWITCH", "ARM_OFF"]);
  });
});

describe("numericFormatKo", () => {
  it("0E-8 → 0", () => {
    expect(formatQuantityKo("0E-8")).toBe("0");
    expect(formatDecimalKo("0E-8")).toBe("0");
    expect(formatPriceKo("0E-8")).toBe("0원");
    expect(formatAmountKo("0E-8")).toBe("0원");
  });

  it("-0E-8 → 0", () => {
    expect(formatQuantityKo("-0E-8")).toBe("0");
  });

  it("1E-8 safe formatting", () => {
    expect(formatQuantityKo("1E-8")).toBe("0.00000001");
  });

  it("quantity precision", () => {
    expect(formatQuantityKo("0.927643780000")).toBe("0.92764378");
  });

  it("price comma", () => {
    expect(formatPriceKo("10780.00000000")).toBe("10,780원");
    expect(formatPriceKo("314.00000000")).toBe("314원");
  });

  it("null/undefined", () => {
    expect(formatQuantityKo(null)).toBe("—");
    expect(formatQuantityKo(undefined)).toBe("—");
    expect(parseDecimalSafe(null)).toBeNull();
  });

  it("cell/formatCellNumeric — no scientific notation", () => {
    expect(cell("0E-8")).toBe("0");
    expect(formatCellNumeric("0E-18")).toBe("0");
    expect(formatCellNumeric("NaN")).toBe("NaN");
  });
});

describe("holdingsRowPolicy", () => {
  it("CLOSED+qty0 AUTO history not shown (no ownership entry)", () => {
    expect(shouldIncludeHoldingPositionRow("0E-8", false)).toBe(false);
    expect(shouldIncludeHoldingPositionRow("0", false)).toBe(false);
  });

  it("OPEN AUTO correctly included", () => {
    expect(shouldIncludeHoldingPositionRow("1.5", true)).toBe(true);
    expect(resolveHoldingOwner("AUTO", true, "1.5")).toBe("AUTO");
  });

  it("MANUAL correctly 일반매매", () => {
    expect(resolveHoldingOwner("MANUAL", true, "10")).toBe("MANUAL");
  });

  it("real mismatch remains 확인 필요", () => {
    expect(resolveHoldingOwner(undefined, false, "5")).toBe("UNKNOWN");
    expect(shouldIncludeHoldingPositionRow("5", false)).toBe(true);
  });

  it("zero qty without ownership → FREE (filtered by holdings filter)", () => {
    expect(resolveHoldingOwner(undefined, false, "0E-8")).toBe("FREE");
  });
});
