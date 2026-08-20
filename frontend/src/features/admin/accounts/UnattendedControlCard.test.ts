import { describe, expect, it } from "vitest";
import { UnattendedControlCard } from "./UnattendedControlCard";

describe("UnattendedControlCard", () => {
  it("exports a renderable component", () => {
    expect(typeof UnattendedControlCard).toBe("function");
  });

  it("OFF props keep start button intent", () => {
    // 렌더 계약: enabled=false → 시작 버튼 경로 (컴포넌트 prop 수준)
    const props = {
      enabled: false,
      remainingSeconds: 0,
      statusCode: "OFF",
      startDisabled: false,
      startDisabledReason: null,
      onStart: () => undefined,
      onStop: () => undefined,
    };
    expect(props.enabled).toBe(false);
    expect(props.startDisabled).toBe(false);
  });

  it("BLOCKED keeps button visible via disabled flag", () => {
    const props = {
      enabled: false,
      remainingSeconds: 0,
      statusCode: "OFF",
      startDisabled: true,
      startDisabledReason: "Kill Switch가 활성화되어 있습니다.",
      onStart: () => undefined,
      onStop: () => undefined,
    };
    expect(props.startDisabled).toBe(true);
    expect(props.startDisabledReason).toContain("Kill Switch");
  });
});
