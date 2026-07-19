import axios from "axios";

import { env } from "@/config/env";
import { apiClient } from "@/lib/api/apiClient";
import type {
  AuthUser,
  AvailabilityResult,
  ChangePasswordRequest,
  LoginRequest,
  LoginResponse,
  SignupRequest,
} from "@/features/auth/types/auth";
import {
  clearRefreshToken,
  getRefreshToken,
  setRefreshToken,
} from "@/lib/storage/tokenStorage";

/** refresh는 인터셉터 순환을 피하기 위해 별도 클라이언트 사용 */
const authBareClient = axios.create({
  baseURL: `${env.API_BASE_URL}${env.API_PREFIX}`,
  timeout: 15_000,
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
  },
});

interface BackendTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: {
    id: string;
    username: string;
    email?: string | null;
    display_name?: string | null;
    roles: string[];
    permissions?: string[];
  };
}

function mapUser(raw: BackendTokenResponse["user"]): AuthUser {
  return {
    id: raw.id,
    username: raw.username,
    email: raw.email ?? undefined,
    displayName: raw.display_name ?? undefined,
    roles: raw.roles ?? [],
    permissions: raw.permissions ?? [],
  };
}

function mapLogin(raw: BackendTokenResponse): LoginResponse {
  return {
    accessToken: raw.access_token,
    refreshToken: raw.refresh_token,
    expiresIn: raw.expires_in,
    user: mapUser(raw.user),
  };
}

export async function loginWithCredentials(
  payload: LoginRequest,
): Promise<LoginResponse> {
  const { data } = await apiClient.post<BackendTokenResponse>("/auth/login", {
    username: payload.username,
    password: payload.password,
  });
  return mapLogin(data);
}

export async function signupWithCredentials(
  payload: SignupRequest,
): Promise<LoginResponse> {
  const { data } = await apiClient.post<BackendTokenResponse>("/auth/signup", {
    name: payload.name,
    username: payload.username,
    email: payload.email,
    password: payload.password,
    password_confirm: payload.passwordConfirm,
    terms_accepted: payload.termsAccepted,
  });
  return mapLogin(data);
}

export async function checkUsernameAvailable(
  username: string,
): Promise<AvailabilityResult> {
  const { data } = await apiClient.get<AvailabilityResult>(
    "/auth/check-username",
    { params: { username } },
  );
  return data;
}

export async function checkEmailAvailable(
  email: string,
): Promise<AvailabilityResult> {
  const { data } = await apiClient.get<AvailabilityResult>("/auth/check-email", {
    params: { email },
  });
  return data;
}

export async function refreshAccessToken(
  refreshToken?: string,
): Promise<LoginResponse> {
  const token = refreshToken ?? getRefreshToken();
  if (!token) {
    throw new Error("Refresh 토큰이 없습니다.");
  }
  const { data } = await authBareClient.post<BackendTokenResponse>(
    "/auth/refresh",
    { refresh_token: token },
  );
  return mapLogin(data);
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const { data } = await apiClient.get<{
    id: string;
    username: string;
    email?: string | null;
    display_name?: string | null;
    roles: string[];
    permissions?: string[];
  }>("/auth/me");
  return mapUser(data);
}

export async function changePassword(payload: ChangePasswordRequest): Promise<void> {
  await apiClient.post("/auth/change-password", {
    current_password: payload.currentPassword,
    new_password: payload.newPassword,
  });
}

export async function logoutRemote(): Promise<void> {
  const refreshToken = getRefreshToken();
  try {
    await apiClient.post("/auth/logout", {
      refresh_token: refreshToken,
    });
  } finally {
    clearRefreshToken();
  }
}

export function persistRefreshToken(token: string | null): void {
  if (!token) {
    clearRefreshToken();
    return;
  }
  setRefreshToken(token);
}
