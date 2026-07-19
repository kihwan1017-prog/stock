export type Nullable<T> = T | null;

export type Optional<T> = T | undefined;

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export type LoadingState = "idle" | "loading" | "success" | "error";

/** API JSON 응답 (구조는 엔드포인트별로 상이) */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };
