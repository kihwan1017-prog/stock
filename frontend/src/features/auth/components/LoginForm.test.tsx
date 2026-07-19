import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const login = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("portal=admin"),
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({
    login,
  }),
}));

vi.mock("@/config/env", () => ({
  env: {
    APP_NAME: "KIKI AI Trading Platform",
    AUTH_MODE: "backend",
  },
}));

import { LoginForm } from "@/features/auth/components/LoginForm";

describe("LoginForm", () => {
  beforeEach(() => {
    login.mockReset();
  });

  it("submits username and password", async () => {
    const user = userEvent.setup();
    login.mockResolvedValue(undefined);
    render(<LoginForm />);

    await user.type(screen.getByLabelText("아이디 또는 이메일"), "admin");
    await user.type(screen.getByLabelText("비밀번호"), "SecurePass1!");
    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(login).toHaveBeenCalledWith(
      {
        username: "admin",
        password: "SecurePass1!",
        rememberMe: true,
      },
      "/admin/dashboard",
    );
  });
});
