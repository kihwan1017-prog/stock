export interface AuthUser {
  id: string;
  username: string;
  displayName?: string;
  roles: string[];
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  accessToken: string;
  user: AuthUser;
}

export interface AuthSession {
  accessToken: string;
  user: AuthUser;
}
