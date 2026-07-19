import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const enterAsDev = vi.fn();
const login = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("portal=admin"),
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({
    login,
    enterAsDev,
  }),
}));

vi.mock("@/config/env", () => ({
  env: {
    APP_NAME: "KIKI AI Trading Platform",
    AUTH_MODE: "disabled",
  },
}));

import { LoginForm } from "@/features/auth/components/LoginForm";

describe("LoginForm", () => {
  beforeEach(() => {
    enterAsDev.mockReset();
    login.mockReset();
  });

  it("shows development enter button when auth is disabled", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);

    const button = screen.getByRole("button", { name: /개발 모드로 입장/ });
    expect(button).toBeInTheDocument();

    await user.click(button);
    expect(enterAsDev).toHaveBeenCalledTimes(1);
  });
});
