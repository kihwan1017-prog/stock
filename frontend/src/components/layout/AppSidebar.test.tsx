import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/dashboard",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/config/env", () => ({
  env: {
    APP_NAME: "KIKI AI Trading Platform",
  },
}));

import { AppSidebar } from "@/components/layout/AppSidebar";

describe("AppSidebar", () => {
  it("renders dashboard menu item", () => {
    render(<AppSidebar collapsed={false} />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("KIKI AI Trading Platform")).toBeInTheDocument();
    expect(screen.getByText("Admin Console")).toBeInTheDocument();
  });

  it("shows short brand when collapsed", () => {
    render(<AppSidebar collapsed />);
    expect(screen.getByText("K")).toBeInTheDocument();
    expect(screen.getByText("v0.1")).toBeInTheDocument();
  });
});
