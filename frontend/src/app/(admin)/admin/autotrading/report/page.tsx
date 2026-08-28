"use client";

import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { AutotradingDailyReportView } from "@/features/admin/autotrading/AutotradingDailyReportView";

export default function AdminAutotradingDailyReportPage() {
  return (
    <AdminPageShell
      title="자동매매 일일 운영보고"
      description="UPBIT·KIWOOM 당일 매매·상태·미거래 사유·장애·Shadow 학습 현황 (조회 전용)."
    >
      <AutotradingDailyReportView />
    </AdminPageShell>
  );
}
