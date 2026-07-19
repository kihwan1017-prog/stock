import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/common/StatusBadge";

describe("StatusBadge", () => {
  it("renders healthy label", () => {
    render(<StatusBadge status="healthy" />);
    expect(screen.getByText("정상")).toBeInTheDocument();
  });

  it("renders custom label", () => {
    render(<StatusBadge status="error" label="연결 실패" />);
    expect(screen.getByText("연결 실패")).toBeInTheDocument();
  });
});
