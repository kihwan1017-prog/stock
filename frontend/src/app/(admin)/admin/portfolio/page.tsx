"use client";

import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { HoldingsOwnershipWorkspace } from "@/features/admin/portfolio/HoldingsOwnershipWorkspace";

export default function AdminPortfolioPage() {
  return (
    <AdminPageShell
      title="보유자산·손익"
      description="일반매매 / 자동매매 ownership 분리 조회 (READ-ONLY)"
    >
      <HoldingsOwnershipWorkspace />
    </AdminPageShell>
  );
}
