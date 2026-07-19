import { env } from "@/config/env";
import type { AuthUser, LoginRequest, LoginResponse } from "@/features/auth/types/auth";

const DEV_DISABLED_TOKEN = "dev-disabled";

/**
 * AUTH_MODE=disabled: 백엔드 호출 없이 개발 세션 생성
 * JWT/회원 API는 Backend에 없음 — 로컬 세션만 사용
 */
export async function enterDevSession(
  portal: "user" | "admin" = "admin",
): Promise<LoginResponse> {
  if (env.AUTH_MODE !== "disabled") {
    throw new Error("enterDevSession은 AUTH_MODE=disabled 에서만 사용할 수 있습니다.");
  }

  const user: AuthUser =
    portal === "user"
      ? {
          id: "dev-user",
          username: "investor",
          displayName: "Dev Investor",
          roles: ["user"],
        }
      : {
          id: "dev",
          username: "dev",
          displayName: "Dev Admin",
          roles: ["admin"],
        };

  return {
    accessToken: DEV_DISABLED_TOKEN,
    user,
  };
}

/**
 * Backend에 /auth/login 이 없어 실패한다. disabled 모드에서만 개발 세션으로 대체.
 */
export async function loginWithCredentials(
  payload: LoginRequest,
): Promise<LoginResponse> {
  void payload;

  if (env.AUTH_MODE === "disabled") {
    return enterDevSession("admin");
  }

  throw new Error(
    "백엔드 인증 API가 아직 없습니다. NEXT_PUBLIC_AUTH_MODE=disabled 를 사용하세요.",
  );
}

export async function logoutRemote(): Promise<void> {
  // Backend logout API 없음
}
