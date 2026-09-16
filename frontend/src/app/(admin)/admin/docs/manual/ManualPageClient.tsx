"use client";

import { Button, Space, Tabs, Typography } from "antd";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { adminRoutes } from "@/config/routes";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { AdminManual } from "@/features/manual/AdminManual";
import { AutoTradingGuide } from "@/features/manual/AutoTradingGuide";
import { SafetyGuide } from "@/features/manual/SafetyGuide";
import { UserManual } from "@/features/manual/UserManual";

type ManualTabKey = "user" | "admin" | "autotrading" | "safety";

const TAB_KEYS: ManualTabKey[] = ["user", "admin", "autotrading", "safety"];

function parseTab(value: string | null): ManualTabKey {
  if (value && TAB_KEYS.includes(value as ManualTabKey)) {
    return value as ManualTabKey;
  }
  return "user";
}

export default function ManualPageClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeTab = parseTab(searchParams.get("tab"));

  const printHref = useMemo(() => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", activeTab);
    return `${adminRoutes.docsManual}?${params.toString()}`;
  }, [activeTab, searchParams]);

  const onTabChange = (key: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", key);
    router.replace(`${pathname}?${params.toString()}`);
  };

  return (
    <AdminPageShell
      title="통합 사용 매뉴얼"
      description="Stock Platform의 사용자 화면과 관리자 화면 사용법, 계좌 등록부터 전략 승인·자동매매·운영관리까지의 절차를 안내합니다."
      extra={
        <Space wrap>
          <Button
            onClick={() => {
              window.open(printHref, "_blank", "noopener,noreferrer");
            }}
          >
            새 창에서 열기
          </Button>
          <Button type="primary" onClick={() => window.print()}>
            인쇄
          </Button>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        Access Key·Secret·계좌번호·토큰은 매뉴얼에 포함하지 않습니다. LIVE Flag는 기본
        OFF이며 임의로 켜도록 안내하지 않습니다.
      </Typography.Paragraph>

      <Tabs
        activeKey={activeTab}
        onChange={onTabChange}
        items={[
          {
            key: "user",
            label: "사용자 매뉴얼",
            children: <UserManual />,
          },
          {
            key: "admin",
            label: "관리자 매뉴얼",
            children: <AdminManual />,
          },
          {
            key: "autotrading",
            label: "자동매매 시작 순서",
            children: <AutoTradingGuide />,
          },
          {
            key: "safety",
            label: "장애 대응 및 안전 종료",
            children: <SafetyGuide />,
          },
        ]}
      />
    </AdminPageShell>
  );
}
