"use client";

import { useQuery } from "@tanstack/react-query";
import { Button, Form, Input, Space } from "antd";
import { useState } from "react";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";

export default function UserNewsPage() {
  const [params, setParams] = useState({ exchange_code: "KRX", symbol: "005930" });

  const news = useQuery({
    queryKey: queryKeys.user.news(params.exchange_code, params.symbol),
    queryFn: () => userApi.getNewsContext(params.exchange_code, params.symbol),
  });

  return (
    <PageContainer
      title="뉴스"
      description="GET /api/v1/news/{exchange}/{symbol} — 심볼 단위 조회만 존재"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form
          layout="inline"
          initialValues={params}
          onFinish={(v: { exchange_code: string; symbol: string }) => setParams(v)}
        >
          <Form.Item name="exchange_code" rules={[{ required: true }]}>
            <Input placeholder="exchange" style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="symbol" rules={[{ required: true }]}>
            <Input placeholder="symbol" style={{ width: 140 }} />
          </Form.Item>
          <Button type="primary" htmlType="submit">
            조회
          </Button>
        </Form>
        <JsonPanel
          title={`GET /api/v1/news/${params.exchange_code}/${params.symbol}`}
          loading={news.isLoading}
          error={news.error ? toApiError(news.error) : null}
          data={news.data}
        />
      </Space>
    </PageContainer>
  );
}
