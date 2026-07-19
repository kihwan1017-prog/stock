"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Form, Input, InputNumber, Space, message } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";
import { useState } from "react";

export default function UserAccountPage() {
  const queryClient = useQueryClient();
  const [paperAccountId, setPaperAccountId] = useState<number | null>(null);

  const broker = useQuery({
    queryKey: queryKeys.user.brokerAccount(),
    queryFn: userApi.getBrokerAccount,
  });
  const kiwoom = useQuery({
    queryKey: queryKeys.user.kiwoomConfig(),
    queryFn: userApi.getKiwoomConfiguration,
  });
  const paperPositions = useQuery({
    queryKey: queryKeys.user.paperPositions(paperAccountId ?? 0),
    queryFn: () => userApi.getPaperPositions(paperAccountId!),
    enabled: paperAccountId !== null && paperAccountId > 0,
  });

  const syncMutation = useMutation({
    mutationFn: userApi.syncKiwoomAccount,
    onSuccess: async () => {
      message.success("키움 계좌 동기화 요청 완료");
      await queryClient.invalidateQueries({ queryKey: queryKeys.user.brokerAccount() });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createPaper = useMutation({
    mutationFn: userApi.createPaperAccount,
    onSuccess: (data) => {
      message.success("모의 계좌 생성 요청 완료");
      const id =
        data && typeof data === "object" && "id" in data && typeof data.id === "number"
          ? data.id
          : data && typeof data === "object" && "account_id" in data
            ? Number((data as { account_id: unknown }).account_id)
            : null;
      if (id && !Number.isNaN(id)) {
        setPaperAccountId(id);
      }
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  return (
    <PageContainer
      title="내 계좌"
      description="기존 브로커·키움·페이퍼 계좌 API를 사용합니다. 회원별 계좌 소유권 API는 없습니다."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="회원별 계좌 목록·연결 CRUD"
          reason="Backend에 사용자 스코프 계좌 목록/소유권 API가 없습니다."
          relatedApis={[
            "GET /api/v1/broker/account",
            "GET /api/v1/kiwoom/configuration",
            "POST /api/v1/paper-accounts",
          ]}
        />

        <Space wrap>
          <Button
            type="primary"
            loading={syncMutation.isPending}
            onClick={() => syncMutation.mutate()}
          >
            키움 계좌 동기화
          </Button>
        </Space>

        <JsonPanel
          title="GET /api/v1/broker/account"
          loading={broker.isLoading}
          error={broker.error ? toApiError(broker.error) : null}
          data={broker.data}
        />
        <JsonPanel
          title="GET /api/v1/kiwoom/configuration"
          loading={kiwoom.isLoading}
          error={kiwoom.error ? toApiError(kiwoom.error) : null}
          data={kiwoom.data}
        />

        <Form
          layout="inline"
          onFinish={(values: {
            account_name: string;
            initial_cash: number;
          }) => createPaper.mutate(values)}
        >
          <Form.Item
            name="account_name"
            rules={[{ required: true, message: "계좌명" }]}
            initialValue="paper-default"
          >
            <Input placeholder="모의 계좌명" />
          </Form.Item>
          <Form.Item
            name="initial_cash"
            rules={[{ required: true }]}
            initialValue={10_000_000}
          >
            <InputNumber min={1} style={{ width: 160 }} />
          </Form.Item>
          <Button type="default" htmlType="submit" loading={createPaper.isPending}>
            POST /paper-accounts
          </Button>
        </Form>

        <Form
          layout="inline"
          onFinish={(values: { account_id: number }) => setPaperAccountId(values.account_id)}
        >
          <Form.Item name="account_id" rules={[{ required: true }]}>
            <InputNumber min={1} placeholder="paper account id" />
          </Form.Item>
          <Button htmlType="submit">포지션 조회</Button>
        </Form>

        {paperAccountId ? (
          <JsonPanel
            title={`GET /api/v1/paper-accounts/${paperAccountId}/positions`}
            loading={paperPositions.isLoading}
            error={paperPositions.error ? toApiError(paperPositions.error) : null}
            data={paperPositions.data}
          />
        ) : null}

        {createPaper.data ? (
          <JsonPanel title="POST /api/v1/paper-accounts 응답" data={createPaper.data} />
        ) : null}
      </Space>
    </PageContainer>
  );
}
