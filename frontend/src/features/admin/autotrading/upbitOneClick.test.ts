import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/admin/api/adminApi", () => ({
  startAdminUbaAutotrading: vi.fn(),
  stopAdminUbaAutotrading: vi.fn(),
}));

import * as adminApi from "@/features/admin/api/adminApi";
import {
  runUpbitOneClickStart,
  runUpbitOneClickStop,
} from "@/features/admin/autotrading/upbitOneClick";

describe("upbitOneClick canonical orchestrator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("start calls single backend start API", async () => {
    vi.mocked(adminApi.startAdminUbaAutotrading).mockResolvedValue({
      status: "READY",
      steps: [{ name: "readiness", status: "PASS", message_ko: "Readiness" }],
      readiness: "READY_FOR_AUTO_TRADING",
    });
    const out = await runUpbitOneClickStart(1380, 17483, {
      reauthorizeUnattended: true,
    });
    expect(adminApi.startAdminUbaAutotrading).toHaveBeenCalledWith(
      1380,
      expect.objectContaining({
        reauthorize_unattended: true,
        strategy_id: 17483,
      }),
    );
    expect(out.ok).toBe(true);
    expect(out.mode).toBe("REAUTHORIZE_START");
    expect(out.steps).toHaveLength(1);
  });

  it("stop defaults to ENTRY_ONLY", async () => {
    vi.mocked(adminApi.stopAdminUbaAutotrading).mockResolvedValue({
      status: "STOPPED",
      steps: [{ name: "protective_keep", status: "PASS" }],
    });
    const out = await runUpbitOneClickStop(1380, 17483);
    expect(adminApi.stopAdminUbaAutotrading).toHaveBeenCalledWith(1380, {
      mode: "ENTRY_ONLY",
      strategy_id: 17483,
    });
    expect(out.ok).toBe(true);
    expect(out.message).toContain("보호");
  });
});
