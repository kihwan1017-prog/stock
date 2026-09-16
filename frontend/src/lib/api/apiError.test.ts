import type { AxiosError } from "axios";
import { describe, expect, it } from "vitest";

import { ApiError, mapAxiosErrorToApiError, toApiError } from "@/lib/api/apiError";

function createAxiosError(data: unknown, status = 400): AxiosError {
  return {
    isAxiosError: true,
    name: "AxiosError",
    message: "Request failed",
    toJSON: () => ({}),
    response: {
      data,
      status,
      statusText: "Bad Request",
      headers: { "x-request-id": "req-1" },
      config: {} as never,
    },
  } as AxiosError;
}

describe("apiError mapper", () => {
  it("maps FastAPI detail string", () => {
    const error = mapAxiosErrorToApiError(createAxiosError({ detail: "Not found" }, 404));
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(404);
    expect(error.message).toBe("Not found");
  });

  it("maps code/message/request_id payload", () => {
    const error = mapAxiosErrorToApiError(
      createAxiosError(
        { code: "VALIDATION_ERROR", message: "Invalid input", request_id: "abc-123" },
        422,
      ),
    );
    expect(error.code).toBe("VALIDATION_ERROR");
    expect(error.message).toBe("Invalid input");
    expect(error.requestId).toBe("abc-123");
  });

  it("maps platform error envelope with nested error.message", () => {
    const error = mapAxiosErrorToApiError(
      createAxiosError(
        {
          ok: false,
          error: { code: "UNAUTHORIZED", message: "아이디 또는 비밀번호가 올바르지 않습니다." },
          detail: null,
          code: "UNAUTHORIZED",
          message: "아이디 또는 비밀번호가 올바르지 않습니다.",
          request_id: "req-login",
        },
        401,
      ),
    );
    expect(error.status).toBe(401);
    expect(error.code).toBe("UNAUTHORIZED");
    expect(error.message).toContain("비밀번호");
    expect(error.requestId).toBe("req-login");
  });

  it("maps Network Error to Korean message", () => {
    const axiosError = {
      isAxiosError: true,
      name: "AxiosError",
      message: "Network Error",
      toJSON: () => ({}),
    } as AxiosError;
    const error = mapAxiosErrorToApiError(axiosError);
    expect(error.status).toBe(0);
    expect(error.message).toBe(
      "네트워크 연결에 실패했습니다. 서버 연결 상태를 확인해주세요.",
    );
  });

  it("maps axios timeout to assistant-friendly Korean message", () => {
    const axiosError = {
      isAxiosError: true,
      name: "AxiosError",
      code: "ECONNABORTED",
      message: "timeout of 15000ms exceeded",
      toJSON: () => ({}),
    } as AxiosError;
    const error = mapAxiosErrorToApiError(axiosError);
    expect(error.message).toBe(
      "AI 답변 생성 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
    );
  });

  it("returns existing ApiError via toApiError", () => {
    const original = new ApiError({ status: 500, message: "boom" });
    expect(toApiError(original)).toBe(original);
  });
});
