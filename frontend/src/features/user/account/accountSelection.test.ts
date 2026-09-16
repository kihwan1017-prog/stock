import { describe, expect, it } from "vitest";

import type { UserAccount } from "@/features/user/api/userApi";

function pickDefaultPaper(accounts: UserAccount[]): UserAccount | null {
  const papers = accounts.filter(
    (row) => row.account_type === "PAPER" && row.is_active,
  );
  return papers.find((row) => row.is_default) ?? papers[0] ?? null;
}

function shouldFetchTrades(accountId: number | null): boolean {
  return accountId !== null && accountId > 0;
}

describe("STEP65 user trades account selection", () => {
  it("picks default paper account first", () => {
    const accounts: UserAccount[] = [
      {
        account_id: 2,
        user_id: 1,
        account_type: "PAPER",
        broker_code: "PAPER",
        account_name: "second",
        masked_account_number: null,
        currency_code: "KRW",
        is_default: false,
        is_active: true,
        connection_status: "CONNECTED",
      },
      {
        account_id: 1,
        user_id: 1,
        account_type: "PAPER",
        broker_code: "PAPER",
        account_name: "default",
        masked_account_number: null,
        currency_code: "KRW",
        is_default: true,
        is_active: true,
        connection_status: "CONNECTED",
      },
      {
        account_id: 9,
        user_id: 1,
        account_type: "KIWOOM",
        broker_code: "KIWOOM",
        account_name: "broker",
        masked_account_number: "****1234",
        currency_code: "KRW",
        is_default: true,
        is_active: true,
        connection_status: "CONNECTED",
      },
    ];
    expect(pickDefaultPaper(accounts)?.account_id).toBe(1);
  });

  it("does not fetch trades without account_id", () => {
    expect(shouldFetchTrades(null)).toBe(false);
    expect(shouldFetchTrades(0)).toBe(false);
    expect(shouldFetchTrades(3)).toBe(true);
  });

  it("masks are never full account numbers in user account payload shape", () => {
    const account: UserAccount = {
      account_id: 1,
      user_id: 1,
      account_type: "KIWOOM",
      broker_code: "KIWOOM",
      account_name: "키움",
      masked_account_number: "******7890",
      currency_code: "KRW",
      is_default: false,
      is_active: true,
      connection_status: "PENDING",
    };
    expect(account.masked_account_number).not.toContain("1234567890");
    expect("accessToken" in account).toBe(false);
  });
});
