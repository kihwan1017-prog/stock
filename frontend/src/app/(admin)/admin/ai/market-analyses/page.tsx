"use client";

/**
 * STEP 11-7 — 시장·차트 AI 분석.
 * 참고용만. 매수/매도/전략/후보/손절 버튼 없음. create ≠ execute.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  App,
} from "antd";
import { useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const DISCLAIMER =
  "AI 분석 결과는 참고용이며, 매수·매도 신호 또는 주문 지시가 아닙니다.";

export default function AdminAiMarketAnalysesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [compareLeft, setCompareLeft] = useState<number | null>(null);
  const [analysisType, setAnalysisType] = useState("SYMBOL_CHART");
  const [exchange, setExchange] = useState("KRX");
  const [symbol, setSymbol] = useState("005930");
  const [timeframe, setTimeframe] = useState("1D");
  const [mode, setMode] = useState("MOCK");
  const [dryResult, setDryResult] = useState("");
  const [compareResult, setCompareResult] = useState("");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiMarketAnalyses(),
    queryFn: () => adminApi.listAiMarketAnalyses(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-market-analysis", selectedId],
    queryFn: () => adminApi.getAiMarketAnalysis(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(asRecord(detailQuery.data)?.analysis);

  const reviewDecisionQuery = useQuery({
    queryKey: ["admin", "ai-review-decision", "CHART", selectedId],
    queryFn: () => adminApi.getAiReviewDecision("CHART", selectedId!),
    enabled: selectedId != null,
    retry: false,
  });
  const reviewDecision = asRecord(asRecord(reviewDecisionQuery.data)?.decision);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-market-analysis-dashboard"],
    queryFn: adminApi.getAiMarketAnalysisDashboard,
  });
  const dash = asRecord(dashQuery.data);

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiMarketAnalyses(),
    });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-market-analysis", selectedId],
      });
    }
  };

  const requireReason = () => {
    if (!reason.trim()) {
      message.error("reason 필요");
      return false;
    }
    return true;
  };

  const createMut = useMutation({
    mutationFn: () =>
      adminApi.createAiMarketAnalysis({
        reason,
        idempotency_key: `fe-mkt-${Date.now()}`,
        analysis_type: analysisType,
        exchange_code: exchange,
        symbol: analysisType === "SYMBOL_CHART" ? symbol : undefined,
        timeframe,
        execution_mode: mode,
        provider_code: mode === "MOCK" ? "mock" : undefined,
      }),
    onSuccess: (data) => {
      message.success("분석 요청 생성 (미실행)");
      const id = asRecord(asRecord(data)?.analysis)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const dryMut = useMutation({
    mutationFn: () =>
      adminApi.dryRunAiMarketAnalysis(selectedId!, { reason }),
    onSuccess: (data) => {
      setDryResult(JSON.stringify(data, null, 2));
      message.success("Dry-run 완료 (외부 호출 0)");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const execMut = useMutation({
    mutationFn: () =>
      adminApi.executeAiMarketAnalysis(selectedId!, {
        reason,
        confirm: mode === "EXTERNAL",
      }),
    onSuccess: () => {
      message.success("실행 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const confirmExecute = () => {
    if (!requireReason() || selectedId == null) return;
    Modal.confirm({
      title: "시장·차트 분석 실행",
      content: (
        <div>
          <p>{DISCLAIMER}</p>
          <p>Mode={mode} / Vision 기본 비활성 / 계좌·주문 데이터 미포함</p>
        </div>
      ),
      onOk: () => execMut.mutateAsync(),
    });
  };

  const runCompare = async () => {
    if (compareLeft == null || selectedId == null) {
      message.error("비교할 두 ID 필요");
      return;
    }
    try {
      const data = await adminApi.compareAiMarketAnalyses({
        left_id: compareLeft,
        right_id: selectedId,
      });
      setCompareResult(JSON.stringify(data, null, 2));
    } catch (e) {
      message.error(toApiError(e).message);
    }
  };

  return (
    <AdminPageShell
      title="시장·차트 분석"
      description="OHLCV Snapshot 기반 AI 분석 (참고용). 수집과 실행 분리. Mock 기본."
    >
      <Alert type="warning" showIcon title={DISCLAIMER} style={{ marginBottom: 16 }} />
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text>
            Chart Today: {cell(dash?.chart_analysis_today)} / Market:{" "}
            {cell(dash?.market_analysis_today)}
          </Typography.Text>
          <Tag>DQ Warn {cell(dash?.data_quality_warning)}</Tag>
          <Tag>Succeeded {cell(dash?.succeeded)}</Tag>
        </Space>

        <Space wrap>
          <Input
            placeholder="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ width: 200 }}
          />
          <Select
            value={analysisType}
            onChange={setAnalysisType}
            options={[
              { value: "SYMBOL_CHART", label: "SYMBOL_CHART" },
              { value: "MARKET_OVERVIEW", label: "MARKET_OVERVIEW" },
            ]}
            style={{ width: 170 }}
          />
          <Select
            value={exchange}
            onChange={setExchange}
            options={[
              { value: "KRX", label: "KRX" },
              { value: "UPBIT", label: "UPBIT" },
            ]}
            style={{ width: 100 }}
          />
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            style={{ width: 120 }}
            disabled={analysisType !== "SYMBOL_CHART"}
          />
          <Select
            value={timeframe}
            onChange={setTimeframe}
            options={[
              { value: "1D", label: "1D" },
              { value: "1m", label: "1m" },
              { value: "5m", label: "5m" },
              { value: "15m", label: "15m" },
            ]}
            style={{ width: 90 }}
          />
          <Select
            value={mode}
            onChange={setMode}
            options={[
              { value: "MOCK", label: "MOCK" },
              { value: "DRY_RUN", label: "DRY_RUN" },
              { value: "EXTERNAL", label: "EXTERNAL" },
            ]}
            style={{ width: 110 }}
          />
          <Button
            type="primary"
            onClick={() => requireReason() && createMut.mutate()}
            loading={createMut.isPending}
          >
            분석 요청 생성
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && dryMut.mutate()}
            loading={dryMut.isPending}
          >
            Dry-run
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={confirmExecute}
            loading={execMut.isPending}
          >
            Execute
          </Button>
        </Space>

        <Table
          rowKey={(r) => String(asRecord(r)?.id ?? "")}
          loading={listQuery.isLoading}
          dataSource={items}
          pagination={{ pageSize: 10 }}
          onRow={(record) => ({
            onClick: () => {
              const id = asRecord(record)?.id;
              if (typeof id === "number") setSelectedId(id);
            },
          })}
          columns={[
            { title: "ID", dataIndex: "id", width: 70 },
            { title: "Type", dataIndex: "analysis_type", width: 140 },
            { title: "Exchange", dataIndex: "exchange_code", width: 90 },
            { title: "Symbol", dataIndex: "symbol", width: 100 },
            { title: "TF", dataIndex: "timeframe", width: 70 },
            { title: "Status", dataIndex: "analysis_status", width: 160 },
            { title: "Quality", dataIndex: "data_quality_status", width: 120 },
            { title: "Trend/Regime", dataIndex: "trend_classification", width: 120 },
            { title: "Mode", dataIndex: "execution_mode", width: 90 },
          ]}
        />

        {detail ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Title level={5}>상세 #{cell(detail.id)}</Typography.Title>
            <Typography.Paragraph type="secondary">{DISCLAIMER}</Typography.Paragraph>
            {reviewDecision ? (
              <Space orientation="vertical" size={4}>
                <Typography.Text strong>AI 분석 품질 승인 상태</Typography.Text>
                <Tag
                  color={
                    reviewDecision.decision === "APPROVED" ||
                    reviewDecision.decision === "APPROVED_WITH_WARNINGS"
                      ? "green"
                      : reviewDecision.decision === "REJECTED"
                        ? "red"
                        : "gold"
                  }
                >
                  {cell(reviewDecision.decision)}
                </Tag>
                <Typography.Link href={adminRoutes.aiReviews}>
                  Human Review 페이지 →
                </Typography.Link>
              </Space>
            ) : null}
            <Typography.Text>
              Status={cell(detail.analysis_status)} / Quality=
              {cell(detail.data_quality_status)} / Candles=
              {cell(detail.candle_count)}
            </Typography.Text>
            <pre style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(detail.safe_result ?? {}, null, 2)}
            </pre>
            <Space>
              <InputNumber
                placeholder="compare left id"
                value={compareLeft ?? undefined}
                onChange={(v) => setCompareLeft(v == null ? null : Number(v))}
              />
              <Button onClick={runCompare}>Compare</Button>
            </Space>
            {compareResult ? (
              <pre style={{ whiteSpace: "pre-wrap" }}>{compareResult}</pre>
            ) : null}
          </Space>
        ) : null}

        {dryResult ? (
          <pre style={{ whiteSpace: "pre-wrap", maxHeight: 240, overflow: "auto" }}>
            {dryResult}
          </pre>
        ) : null}
      </Space>
    </AdminPageShell>
  );
}
