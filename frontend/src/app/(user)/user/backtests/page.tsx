"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Form, Input, InputNumber, Space, message } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";

export default function UserBacktestsPage() {
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: queryKeys.user.backtestRuns(),
    queryFn: userApi.listBacktestRuns,
  });

  const runMa = useMutation({
    mutationFn: userApi.runMovingAverageBacktest,
    onSuccess: async () => {
      message.success("moving-average backtest 요청 완료");
      await queryClient.invalidateQueries({ queryKey: queryKeys.user.backtestRuns() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <PageContainer
      title="백테스트"
      description="GET /backtest-runs · POST /backtests/moving-average (스키마는 /docs 확인)"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form
          layout="vertical"
          style={{ maxWidth: 480 }}
          onFinish={(values) => runMa.mutate(values)}
          initialValues={{
            exchange_code: "KRX",
            symbol: "005930",
            short_window: 5,
            long_window: 20,
          }}
        >
          <Form.Item name="exchange_code" label="exchange_code" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="symbol" label="symbol" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="short_window" label="short_window">
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="long_window" label="long_window">
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={runMa.isPending}>
            POST /api/v1/backtests/moving-average
          </Button>
        </Form>
        {runMa.data ? (
          <JsonPanel title="moving-average 응답" data={runMa.data} />
        ) : null}
        <JsonPanel
          title="GET /api/v1/backtest-runs"
          loading={runs.isLoading}
          error={runs.error ? toApiError(runs.error) : null}
          data={runs.data}
        />
      </Space>
    </PageContainer>
  );
}
