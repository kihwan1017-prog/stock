import { beforeEach, describe, expect, it } from "vitest";

import {
  clearRefreshToken,
  clearToken,
  getRefreshToken,
  getToken,
  setRefreshToken,
  setToken,
  tokenStorageKey,
} from "@/lib/storage/tokenStorage";

describe("tokenStorage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("stores and reads access token from sessionStorage", () => {
    setToken("access-token");
    expect(getToken()).toBe("access-token");
    expect(sessionStorage.getItem(tokenStorageKey)).toBe("access-token");
  });

  it("stores and clears refresh token", () => {
    setRefreshToken("refresh-token");
    expect(getRefreshToken()).toBe("refresh-token");
    clearRefreshToken();
    expect(getRefreshToken()).toBeNull();
  });

  it("clears access token", () => {
    setToken("access-token");
    clearToken();
    expect(getToken()).toBeNull();
  });
});
