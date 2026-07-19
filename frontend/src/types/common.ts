export type Nullable<T> = T | null;

export type Optional<T> = T | undefined;

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export type LoadingState = "idle" | "loading" | "success" | "error";
