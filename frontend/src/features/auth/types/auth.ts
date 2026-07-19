export interface AuthUser {
  id: string;
  username: string;
  email?: string;
  displayName?: string;
  roles: string[];
  permissions: string[];
}

export interface LoginRequest {
  username: string;
  password: string;
  rememberMe?: boolean;
}

export interface SignupRequest {
  name: string;
  username: string;
  email: string;
  password: string;
  passwordConfirm: string;
  termsAccepted: boolean;
}

export interface LoginResponse {
  accessToken: string;
  refreshToken: string;
  expiresIn?: number;
  user: AuthUser;
}

export interface ChangePasswordRequest {
  currentPassword: string;
  newPassword: string;
}

export interface AuthSession {
  accessToken: string;
  refreshToken?: string;
  user: AuthUser;
}

export interface AvailabilityResult {
  available: boolean;
  field: string;
  value: string;
}
