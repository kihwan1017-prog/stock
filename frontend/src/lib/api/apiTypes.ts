export interface ApiErrorPayload {
  status: number;
  code?: string;
  message: string;
  details?: unknown;
  requestId?: string;
}

export interface ApiSuccessEnvelope<T> {
  data: T;
  message?: string;
  request_id?: string;
}

export interface HealthResponse {
  status: string;
  service?: string;
  timestamp?: string;
}
