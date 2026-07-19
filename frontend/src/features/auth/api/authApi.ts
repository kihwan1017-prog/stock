import { env } from "@/config/env";
import type { AuthUser, LoginRequest, LoginResponse } from "@/features/auth/types/auth";

const DEV_DISABLED_TOKEN = "dev-disabled";

const DEV_USER: AuthUser = {
  id: "dev",
  username: "dev",
  displayName: "Dev Admin",
  roles: ["admin"],
};

/**
 * AUTH_MODE=disabled: 백엔드 호출 없이 개발 세션 생성
 * TODO(STEP50): 실제 JWT/로그인 API 연동
 */
export async function enterDevSession(): Promise<LoginResponse> {
  if (env.AUTH_MODE !== "disabled") {
    throw new Error("enterDevSession은 AUTH_MODE=disabled 에서만 사용할 수 있습니다.");
  }

  return {
    accessToken: DEV_DISABLED_TOKEN,
    user: DEV_USER,
  };
}

/**
 * TODO(STEP50): FastAPI 인증 API가 준비되면 실제 로그인 호출로 교체
 */
export async function loginWithCredentials(
  payload: LoginRequest,
): Promise<LoginResponse> {
  void payload;

  if (env.AUTH_MODE === "disabled") {
    return enterDevSession();
  }

  // TODO(STEP50): apiClient.post('/auth/login', payload)
  throw new Error(
    "백엔드 인증 API가 아직 없습니다. NEXT_PUBLIC_AUTH_MODE=disabled 를 사용하세요.",
  );
}

export async function logoutRemote(): Promise<void> {
  // TODO(STEP50): 서버 세션 무효화 API 호출
}
