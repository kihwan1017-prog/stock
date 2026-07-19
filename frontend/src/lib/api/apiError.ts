import axios, { type AxiosError } from "axios";

import type { ApiErrorPayload } from "@/lib/api/apiTypes";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;
  readonly requestId?: string;

  constructor(payload: ApiErrorPayload) {
    super(payload.message);
    this.name = "ApiError";
    this.status = payload.status;
    this.code = payload.code;
    this.details = payload.details;
    this.requestId = payload.requestId;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function extractMessage(data: unknown): string | undefined {
  if (typeof data === "string" && data.trim().length > 0) {
    return data;
  }

  if (!isRecord(data)) {
    return undefined;
  }

  // FastAPI 표준: { detail: string | object | array }
  if (typeof data.detail === "string" && data.detail.trim().length > 0) {
    return data.detail;
  }

  if (Array.isArray(data.detail)) {
    const messages = data.detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (isRecord(item) && typeof item.msg === "string") {
          return item.msg;
        }
        return null;
      })
      .filter((item): item is string => item !== null);
    if (messages.length > 0) {
      return messages.join("; ");
    }
  }

  if (isRecord(data.detail) && typeof data.detail.message === "string") {
    return data.detail.message;
  }

  // 공통 플랫폼 형식: { code, message, request_id }
  if (typeof data.message === "string" && data.message.trim().length > 0) {
    return data.message;
  }

  return undefined;
}

function extractCode(data: unknown): string | undefined {
  if (!isRecord(data)) {
    return undefined;
  }
  if (typeof data.code === "string") {
    return data.code;
  }
  if (isRecord(data.detail) && typeof data.detail.code === "string") {
    return data.detail.code;
  }
  return undefined;
}

function extractRequestId(data: unknown, headers?: Record<string, unknown>): string | undefined {
  if (isRecord(data)) {
    if (typeof data.request_id === "string") {
      return data.request_id;
    }
    if (typeof data.requestId === "string") {
      return data.requestId;
    }
    if (isRecord(data.detail) && typeof data.detail.request_id === "string") {
      return data.detail.request_id;
    }
  }

  const headerValue = headers?.["x-request-id"];
  return typeof headerValue === "string" ? headerValue : undefined;
}

export function mapAxiosErrorToApiError(error: AxiosError): ApiError {
  const status = error.response?.status ?? 0;
  const data = error.response?.data;
  const headers = error.response?.headers as Record<string, unknown> | undefined;

  const message =
    extractMessage(data) ??
    error.message ??
    (status === 0 ? "네트워크 연결에 실패했습니다." : "요청 처리 중 오류가 발생했습니다.");

  return new ApiError({
    status,
    code: extractCode(data),
    message,
    details: data,
    requestId: extractRequestId(data, headers),
  });
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }

  if (axios.isAxiosError(error)) {
    return mapAxiosErrorToApiError(error);
  }

  if (error instanceof Error) {
    return new ApiError({
      status: 0,
      message: error.message || "알 수 없는 오류가 발생했습니다.",
    });
  }

  return new ApiError({
    status: 0,
    message: "알 수 없는 오류가 발생했습니다.",
    details: error,
  });
}
