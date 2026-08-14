"use client";

import { Space } from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { UpbitHubOpsSection } from "@/features/admin/upbit/UpbitHubOpsSection";
import { UpbitHubTabs } from "@/features/admin/upbit/UpbitHubTabs";
import { UpbitLiveStatusReadSummary } from "@/features/admin/upbit/UpbitLiveStatusReadSummary";
import { UpbitNewsCombinedShadowPanel } from "@/features/admin/upbit/UpbitNewsCombinedShadowPanel";
import { UpbitNewsNoticeCollectorPanel } from "@/features/admin/upbit/UpbitNewsNoticeCollectorPanel";
import { UpbitOpportunityScannerPanel } from "@/features/admin/upbit/UpbitOpportunityScannerPanel";

/** M5-A: Tab shell + 패널 재배치. 패널 내부 로직/API는 변경하지 않음. */
export default function AdminUpbitPage() {
  return (
    <AdminPageShell
      title="업비트 계좌"
      description="UPBIT Hub — Scanner / News / A-B / 운영 정합. LIVE/ARM 제어는 계좌 관리에서 수행합니다."
      extra={
        <Space wrap>
          <Link href={adminRoutes.accounts}>계좌 관리 (LIVE/ARM 제어)</Link>
        </Space>
      }
    >
      <UpbitHubTabs
        liveSummary={<UpbitLiveStatusReadSummary />}
        technical={<UpbitOpportunityScannerPanel />}
        news={<UpbitNewsNoticeCollectorPanel />}
        ab={<UpbitNewsCombinedShadowPanel />}
        ops={<UpbitHubOpsSection />}
      />
    </AdminPageShell>
  );
}
