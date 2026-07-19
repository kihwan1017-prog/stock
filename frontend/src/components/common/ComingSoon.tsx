"use client";

import { Result } from "antd";

import { PageContainer } from "@/components/common/PageContainer";

interface ComingSoonProps {
  title: string;
  description?: string;
}

export function ComingSoon({ title, description }: ComingSoonProps) {
  return (
    <PageContainer title={title} description={description}>
      <Result
        status="info"
        title="Coming Soon"
        subTitle="이 화면은 STEP42 이후 단계에서 구현됩니다."
      />
    </PageContainer>
  );
}
