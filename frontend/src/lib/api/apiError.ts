import axios, { type AxiosError } from "axios";

import type { ApiErrorPayload } from "@/lib/api/apiTypes";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;
  readonly requestId?: string;

  constructor(payload: ApiErrorPayload) {
    // 빈/비문자 메시지는 Error 생성 시 이상 동작·오버레이 혼란을 막기 위해 정규화
    const normalizedMessage =
      typeof payload.message === "string" && payload.message.trim().length > 0
        ? payload.message.trim()
        : "요청 처리 중 오류가 발생했습니다.";
    super(normalizedMessage);
    this.name = "ApiError";
    this.status = Number.isFinite(payload.status) ? payload.status : 0;
    this.code = payload.code;
    this.details = payload.details;
    this.requestId = payload.requestId;
    // bundler/transpile 환경에서 instanceof 유지
    Object.setPrototypeOf(this, ApiError.prototype);
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

  // { ok:false, error:{ code, message } }
  if (isRecord(data.error) && typeof data.error.message === "string") {
    return data.error.message;
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
  if (typeof data.error_code === "string") {
    return data.error_code;
  }
  if (isRecord(data.error) && typeof data.error.code === "string") {
    return data.error.code;
  }
  if (isRecord(data.detail) && typeof data.detail.error_code === "string") {
    return data.detail.error_code;
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

function resolveFallbackMessage(status: number, axiosMessage?: string): string {
  if (typeof axiosMessage === "string" && axiosMessage.trim().length > 0) {
    // Axios 기본 "Network Error" 등은 한글로 치환
    if (axiosMessage === "Network Error" || status === 0) {
      return "네트워크 연결에 실패했습니다.";
    }
    return axiosMessage;
  }
  return status === 0
    ? "네트워크 연결에 실패했습니다."
    : "요청 처리 중 오류가 발생했습니다.";
}

export function mapAxiosErrorToApiError(error: AxiosError): ApiError {
  const status = error.response?.status ?? 0;
  const data = error.response?.data;
  const headers = error.response?.headers as Record<string, unknown> | undefined;

  const message = extractMessage(data) ?? resolveFallbackMessage(status, error.message);

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
