/**
 * Alert preference draft/save regression — save→revert 방지.
 */
import { describe, expect, it } from "vitest";

import {
  UNIQUE_DISABLE_KEYS,
  USER_REQUESTED_DISABLE,
  buildBulkSavePayloadAfterToggles,
  dirtyPreferences,
  enabledMapFromItems,
  filterPreferenceItems,
  isDirty,
  resolveUxMeta,
} from "./alertPreferenceUx";

describe("alertPreferenceUx save persistence", () => {
  it("TEST A: last toggle OFF persists in bulk payload (no revert)", () => {
    const initial = { A: true, B: true, C: true };
    const payload = buildBulkSavePayloadAfterToggles(initial, [
      { key: "A", enabled: false },
      { key: "B", enabled: false },
      { key: "C", enabled: false },
    ]);
    expect(payload).toEqual({ A: false, B: false, C: false });
    const draft = { A: false, B: false, C: false };
    expect(isDirty(draft, initial)).toBe(true);
    // save 성공 후 baseline=draft → dirty false, C 유지
    expect(isDirty(draft, draft)).toBe(false);
    expect(draft.C).toBe(false);
  });

  it("TEST B: last toggle ON persists", () => {
    const initial = { A: false, B: false, C: false };
    const payload = buildBulkSavePayloadAfterToggles(initial, [
      { key: "A", enabled: true },
      { key: "B", enabled: true },
      { key: "C", enabled: true },
    ]);
    expect(payload).toEqual({ A: true, B: true, C: true });
  });

  it("TEST C: SYSTEM/UPBIT AI share preference_key — no scope collision", () => {
    const systemIntent = USER_REQUESTED_DISABLE.find(
      (x) => x.intent === "SYSTEM_AI_TRADING_DECISION",
    );
    const upbitIntent = USER_REQUESTED_DISABLE.find(
      (x) => x.intent === "UPBIT_AI_TRADING_DECISION",
    );
    expect(systemIntent?.preference_key).toBe("UPBIT_AI_DECISION");
    expect(upbitIntent?.preference_key).toBe("UPBIT_AI_DECISION");
    expect(UNIQUE_DISABLE_KEYS).toContain("UPBIT_AI_DECISION");
    expect(UNIQUE_DISABLE_KEYS).not.toContain("KIWOOM_AI_DECISION");

    const initial = {
      UPBIT_AI_DECISION: false,
      KIWOOM_AI_DECISION: true,
    };
    const payload = dirtyPreferences(
      { ...initial, UPBIT_AI_DECISION: false },
      initial,
    );
    // 이미 false → dirty 없음; KIWOOM 유지
    expect(payload).toEqual({});
    const after = dirtyPreferences(
      { UPBIT_AI_DECISION: false, KIWOOM_AI_DECISION: true },
      { UPBIT_AI_DECISION: true, KIWOOM_AI_DECISION: true },
    );
    expect(after).toEqual({ UPBIT_AI_DECISION: false });
    expect(after.KIWOOM_AI_DECISION).toBeUndefined();
  });

  it("TEST D: multi-change then save — refetch baseline sync keeps values", () => {
    const initial = enabledMapFromItems([
      {
        key: "AUTO_SLOT",
        group: "SYSTEM",
        label: "x",
        description: "",
        enabled: true,
      },
      {
        key: "UPBIT_AI_DECISION",
        group: "SYSTEM",
        label: "y",
        description: "",
        enabled: true,
      },
    ]);
    const draft = { ...initial, AUTO_SLOT: false, UPBIT_AI_DECISION: false };
    const payload = dirtyPreferences(draft, initial);
    expect(payload).toEqual({
      AUTO_SLOT: false,
      UPBIT_AI_DECISION: false,
    });
    // response items → new baseline
    const saved = enabledMapFromItems([
      {
        key: "AUTO_SLOT",
        group: "SYSTEM",
        label: "x",
        description: "",
        enabled: false,
      },
      {
        key: "UPBIT_AI_DECISION",
        group: "SYSTEM",
        label: "y",
        description: "",
        enabled: false,
      },
    ]);
    expect(isDirty(saved, saved)).toBe(false);
    expect(saved.AUTO_SLOT).toBe(false);
    expect(saved.UPBIT_AI_DECISION).toBe(false);
  });

  it("TEST E: failed save keeps draft dirty for retry", () => {
    const baseline = { A: true, B: true };
    const draft = { A: false, B: false };
    // API 실패 시 baseline 유지 → dirty 유지
    expect(isDirty(draft, baseline)).toBe(true);
    expect(dirtyPreferences(draft, baseline)).toEqual({
      A: false,
      B: false,
    });
  });

  it("UX meta uses preference_key not display name", () => {
    const upbitAi = resolveUxMeta({
      key: "UPBIT_AI_DECISION",
      group: "SYSTEM",
      label: "UPBIT AI 매매 판단 변경",
      description: "",
      enabled: true,
    });
    expect(upbitAi.source).toBe("UPBIT");
    expect(upbitAi.uxGroup).toBe("ANALYSIS");
    expect(upbitAi.userLabel).toBe("AI 매매 판단 변경");
  });

  it("source filter separates UPBIT analysis from KIWOOM", () => {
    const items = [
      {
        key: "UPBIT_AI_DECISION",
        group: "SYSTEM",
        label: "a",
        description: "",
        enabled: true,
      },
      {
        key: "KIWOOM_AI_DECISION",
        group: "SYSTEM",
        label: "b",
        description: "",
        enabled: true,
      },
    ];
    const upbitOnly = filterPreferenceItems(items, "UPBIT", "ALL");
    expect(upbitOnly.map((i) => i.key)).toEqual(["UPBIT_AI_DECISION"]);
  });
});
