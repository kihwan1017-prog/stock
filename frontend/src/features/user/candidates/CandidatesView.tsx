"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Empty, Select, Space, Table, Typography } from "antd";
import Link from "next/link";
import { useState } from "react";

import { userRoutes } from "@/config/routes";
import * as userApi from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

interface CandidateRow {
  rank_no?: number;
  symbol: string;
  trade_date?: string;
  total_score?: number;
  [key: string]: unknown;
}

interface CandidatesResponse {
  run_id?: number;
  exchange_code?: string;
  as_of_date?: string;
  selected_count?: number;
  candidates?: CandidateRow[];
}

function todayKst(): string {
  // 백엔드 as_of_date는 KST 로컬 날짜 기준
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
}

interface CandidatesViewProps {
  title: string;
  /** 거래소 코드 (예: KRX, UPBIT) */
  exchangeCode: string;
  description?: string;
  /** 지정 시 상단에 시장 선택 셀렉트를 노출 (예: 주식화면의 KRX/KOSDAQ) */
  exchangeOptions?: string[];
}

/**
 * 매매 후보 화면 — 주식·업비트 공용 컴포넌트.
 * 저장된 최신 배치 결과(GET /user/candidates/latest)를 우선 조회하고,
 * 없으면(404) 당일 스크리닝(GET /user/candidates/top)을 사용자가 직접 실행할 수 있게 한다.
 * Mock 데이터는 사용하지 않는다.
 */
export function CandidatesView({
  title,
  exchangeCode: initialExchangeCode,
  description,
  exchangeOptions,
}: CandidatesViewProps) {
  const [exchangeCode, setExchangeCode] = useState(initialExchangeCode);
  const [screenedResult, setScreenedResult] = useState<CandidatesResponse | null>(
    null,
  );

  const latestQuery = useQuery({
    queryKey: queryKeys.user.latestCandidates(exchangeCode),
    queryFn: () =>
      userApi.getLatestCandidates(exchangeCode) as Promise<CandidatesResponse>,
    retry: false,
  });

  const latestError = latestQuery.error ? toApiError(latestQuery.error) : null;
  const latestNotFound = latestError?.status === 404;

  const screenMutation = useMutation({
    mutationFn: () =>
      userApi.getTopCandidates(
        exchangeCode,
        todayKst(),
      ) as Promise<CandidatesResponse>,
    onSuccess: (data) => setScreenedResult(data),
  });

  const switchExchange = (value: string) => {
    setExchangeCode(value);
    setScreenedResult(null);
  };

  const activeData: CandidatesResponse | null =
    screenedResult ??
    (latestNotFound ? null : (latestQuery.data as CandidatesResponse | undefined) ?? null);
  const rows = activeData?.candidates ?? [];
  const isLoading = latestQuery.isLoading || screenMutation.isPending;

  return (
    <UserPageShell title={title} description={description}>
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="데이터 안내"
          description="저장된 최신 배치 결과(latest)가 없으면 「당일 스크리닝 실행」으로 즉시 계산할 수 있습니다. 즉시 계산은 서버 부하가 있으니 반복 실행은 자제해 주세요."
        />

        <Card size="small">
          <Space wrap>
            {exchangeOptions && exchangeOptions.length > 1 ? (
              <Select
                style={{ width: 140 }}
                value={exchangeCode}
                onChange={switchExchange}
                options={exchangeOptions.map((code) => ({
                  value: code,
                  label: code,
                }))}
              />
            ) : null}
            <Button
              type="primary"
              loading={screenMutation.isPending}
              onClick={() => screenMutation.mutate()}
            >
              당일 스크리닝 실행
            </Button>
            <Button
              onClick={() => void latestQuery.refetch()}
              loading={latestQuery.isFetching}
            >
              최신 결과 새로고침
            </Button>
            <Link href={userRoutes.ai}>
              <Button>AI 추천 보기</Button>
            </Link>
          </Space>
        </Card>

        {latestError && !latestNotFound ? (
          <Alert type="error" showIcon title={latestError.message} />
        ) : null}

        {screenMutation.isError ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(screenMutation.error).message}
          />
        ) : null}

        <Card
          title={screenedResult ? "당일 스크리닝 결과" : "최신 저장 결과"}
          size="small"
          extra={
            activeData ? (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {activeData.exchange_code ?? exchangeCode} · 기준일{" "}
                {activeData.as_of_date ?? "-"} ·{" "}
                {activeData.selected_count ?? rows.length}건
              </Typography.Text>
            ) : null
          }
        >
          {rows.length === 0 && !isLoading ? (
            <Empty
              description={
                latestNotFound
                  ? "저장된 최신 후보 결과가 없습니다. 「당일 스크리닝 실행」으로 지금 계산해 보세요."
                  : "매매 후보가 없습니다."
              }
            />
          ) : (
            <Table<CandidateRow>
              size="small"
              loading={isLoading}
              rowKey={(row) =>
                String(row.symbol ?? row.rank_no ?? JSON.stringify(row))
              }
              dataSource={rows}
              pagination={{ pageSize: 20 }}
              locale={{ emptyText: "매매 후보가 없습니다." }}
              columns={[
                {
                  title: "순위",
                  width: 70,
                  render: (_value, row, index) => row.rank_no ?? index + 1,
                },
                { title: "종목", dataIndex: "symbol" },
                {
                  title: "점수",
                  dataIndex: "total_score",
                  render: (value: number) =>
                    typeof value === "number" ? value.toFixed(2) : "-",
                },
                {
                  title: "기준일",
                  dataIndex: "trade_date",
                  render: (value?: string) =>
                    value ?? activeData?.as_of_date ?? "-",
                },
              ]}
            />
          )}
        </Card>

        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
          GET /user/candidates/latest/{"{exchange_code}"} · GET
          /user/candidates/top/{"{exchange_code}"}
        </Typography.Paragraph>
      </Space>
    </UserPageShell>
  );
}
