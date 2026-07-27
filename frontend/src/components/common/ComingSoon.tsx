"use client";

import { Result } from "antd";

import { PageContainer } from "@/components/common/PageContainer";

interface ComingSoonProps {
  title: string;
  /** 미구현 사유 — 화면에 그대로 표시 */
  description?: string;
}

export function ComingSoon({ title, description }: ComingSoonProps) {
  return (
    <PageContainer title={title} description={description}>
      <Result
        status="info"
        title="준비 중"
        subTitle={
          description ??
          "이 화면은 아직 구현되지 않았습니다. Mock 데이터로 대체하지 않습니다."
        }
      />
    </PageContainer>
  );
}
