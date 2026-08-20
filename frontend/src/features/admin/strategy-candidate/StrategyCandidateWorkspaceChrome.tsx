"use client";

/**
 * 전략·후보 Workspace 상단 크롬 — 역할 설명 + Tab 네비게이션.
 * 기존 page.tsx / API는 그대로 두고 라우트만 전환한다.
 */

import { Alert, Tabs } from "antd";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import {
  findStrategyCandidateWorkspace,
  resolveStrategyCandidateTabKey,
} from "@/features/admin/strategy-candidate/strategyCandidateWorkspaceConfig";

type Props = {
  children: ReactNode;
};

export function StrategyCandidateWorkspaceChrome({ children }: Props) {
  const pathname = usePathname();
  const router = useRouter();
  const workspace = findStrategyCandidateWorkspace(pathname);

  if (!workspace) {
    return <>{children}</>;
  }

  const activeKey = resolveStrategyCandidateTabKey(workspace, pathname);

  return (
    <>
      <div
        data-testid="strategy-candidate-workspace-chrome"
        style={{ padding: "16px 24px 0" }}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          title={workspace.label}
          description={workspace.description}
        />
        <Tabs
          activeKey={activeKey}
          onChange={(key) => {
            const tab = workspace.tabs.find((item) => item.key === key);
            if (tab?.href && tab.href !== pathname) {
              router.push(tab.href);
            }
          }}
          items={workspace.tabs.map((tab) => ({
            key: tab.key,
            label: tab.label,
          }))}
        />
      </div>
      {children}
    </>
  );
}
