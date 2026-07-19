import { beforeEach, describe, expect, it } from "vitest";

import { clearToken, getToken, setToken, tokenStorageKey } from "@/lib/storage/tokenStorage";

describe("tokenStorage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("stores and reads token from sessionStorage", () => {
    setToken("dev-disabled");
    expect(getToken()).toBe("dev-disabled");
    expect(sessionStorage.getItem(tokenStorageKey)).toBe("dev-disabled");
  });

  it("clears token", () => {
    setToken("dev-disabled");
    clearToken();
    expect(getToken()).toBeNull();
  });
});
