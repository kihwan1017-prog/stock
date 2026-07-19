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

  it("returns existing ApiError via toApiError", () => {
    const original = new ApiError({ status: 500, message: "boom" });
    expect(toApiError(original)).toBe(original);
  });
});
