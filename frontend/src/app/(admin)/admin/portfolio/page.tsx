"use client";

import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { HoldingsOwnershipWorkspace } from "@/features/admin/portfolio/HoldingsOwnershipWorkspace";

export default function AdminPortfolioPage() {
  return (
    <AdminPageShell
      title="보유자산·손익"
      description="시장(업비트/키움) · 일반매매/자동매매 분리 조회 (READ-ONLY)"
    >
      <HoldingsOwnershipWorkspace />
    </AdminPageShell>
  );
}
