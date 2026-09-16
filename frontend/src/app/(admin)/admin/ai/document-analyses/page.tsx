"use client";

/**
 * STEP 11-6 — 뉴스·공시 AI 문서 분석.
 * 참고용만. 매수/매도/전략/후보 버튼 없음. create ≠ execute.
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
  "AI 분석 결과는 참고용이며 매매 신호 또는 주문 지시가 아닙니다.";

export default function AdminAiDocumentAnalysesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [compareLeft, setCompareLeft] = useState<number | null>(null);
  const [documentType, setDocumentType] = useState("NEWS");
  const [sourceId, setSourceId] = useState<number>(1);
  const [mode, setMode] = useState("MOCK");
  const [maxTokens, setMaxTokens] = useState(256);
  const [dryResult, setDryResult] = useState("");
  const [compareResult, setCompareResult] = useState("");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiDocumentAnalyses(),
    queryFn: () => adminApi.listAiDocumentAnalyses(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-document-analysis", selectedId],
    queryFn: () => adminApi.getAiDocumentAnalysis(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(asRecord(detailQuery.data)?.analysis);

  const reviewDecisionQuery = useQuery({
    queryKey: ["admin", "ai-review-decision", "NEWS", selectedId],
    queryFn: () => adminApi.getAiReviewDecision("NEWS", selectedId!),
    enabled: selectedId != null,
    retry: false,
  });
  const reviewDecision = asRecord(asRecord(reviewDecisionQuery.data)?.decision);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-document-analysis-dashboard"],
    queryFn: adminApi.getAiDocumentAnalysisDashboard,
  });
  const dash = asRecord(dashQuery.data);

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiDocumentAnalyses(),
    });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-document-analysis", selectedId],
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
      adminApi.createAiDocumentAnalysis({
        reason,
        idempotency_key: `fe-doc-${Date.now()}`,
        document_type: documentType,
        source_document_id: sourceId,
        execution_mode: mode,
        provider_code: mode === "MOCK" ? "mock" : undefined,
        max_tokens: maxTokens,
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
      adminApi.dryRunAiDocumentAnalysis(selectedId!, { reason }),
    onSuccess: (data) => {
      setDryResult(JSON.stringify(data, null, 2));
      message.success("Dry-run 완료 (외부 호출 0)");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const execMut = useMutation({
    mutationFn: () =>
      adminApi.executeAiDocumentAnalysis(selectedId!, {
        reason,
        confirm: mode === "EXTERNAL",
      }),
    onSuccess: () => {
      message.success("실행 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const reanalyzeMut = useMutation({
    mutationFn: () =>
      adminApi.reanalyzeAiDocumentAnalysis(selectedId!, { reason }),
    onSuccess: (data) => {
      message.success("재분석 생성 (이전 결과 SUPERSEDED)");
      const id = asRecord(asRecord(data)?.analysis)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const confirmExecute = () => {
    if (!requireReason() || selectedId == null) return;
    Modal.confirm({
      title: "문서 분석 실행",
      content: (
        <div>
          <p>{DISCLAIMER}</p>
          <p>
            Mode={mode} / max_tokens={maxTokens} / 원본 외부 전송 가능
          </p>
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
      const data = await adminApi.compareAiDocumentAnalyses({
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
      title="문서 분석"
      description="뉴스·공시 AI 분석 (참고용). 수집과 실행 분리. Mock 기본."
    >
      <Alert type="warning" showIcon title={DISCLAIMER} style={{ marginBottom: 16 }} />
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text>
            Today News: {cell(dash?.news_analysis_today)} / Disclosure:{" "}
            {cell(dash?.disclosure_analysis_today)}
          </Typography.Text>
          <Tag>Succeeded {cell(dash?.succeeded)}</Tag>
          <Tag>Failed {cell(dash?.failed)}</Tag>
          <Tag>Blocked {cell(dash?.blocked)}</Tag>
        </Space>

        <Space wrap>
          <Input
            placeholder="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ width: 220 }}
          />
          <Select
            value={documentType}
            onChange={setDocumentType}
            options={[
              { value: "NEWS", label: "NEWS" },
              { value: "DISCLOSURE", label: "DISCLOSURE" },
            ]}
            style={{ width: 140 }}
          />
          <Space.Compact>
            <Input style={{ width: 88 }} value="source_id" disabled />
            <InputNumber
              min={1}
              value={sourceId}
              onChange={(v) => setSourceId(Number(v || 1))}
            />
          </Space.Compact>
          <Select
            value={mode}
            onChange={setMode}
            options={[
              { value: "MOCK", label: "MOCK" },
              { value: "DRY_RUN", label: "DRY_RUN" },
              { value: "EXTERNAL", label: "EXTERNAL" },
            ]}
            style={{ width: 120 }}
          />
          <InputNumber
            min={32}
            max={2048}
            value={maxTokens}
            onChange={(v) => setMaxTokens(Number(v || 256))}
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
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && reanalyzeMut.mutate()}
            loading={reanalyzeMut.isPending}
          >
            Reanalyze
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
            { title: "Type", dataIndex: "document_type", width: 110 },
            { title: "Source", dataIndex: "source_document_key", ellipsis: true },
            { title: "상태", dataIndex: "analysis_status", width: 160 },
            { title: "Mode", dataIndex: "execution_mode", width: 90 },
            { title: "Provider", dataIndex: "provider_code", width: 90 },
            { title: "신뢰도", dataIndex: "confidence", width: 100 },
            { title: "종목", dataIndex: "symbol", width: 90 },
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
              Status={cell(detail.analysis_status)} / Provider=
              {cell(detail.provider_code)} / Model={cell(detail.model)}
            </Typography.Text>
            <Typography.Paragraph>
              <pre style={{ whiteSpace: "pre-wrap" }}>
                {JSON.stringify(detail.safe_result ?? {}, null, 2)}
              </pre>
            </Typography.Paragraph>
            <Space>
              <InputNumber
                placeholder="compare left id"
                value={compareLeft ?? undefined}
                onChange={(v) => setCompareLeft(v == null ? null : Number(v))}
              />
              <Button onClick={runCompare}>Compare with selected</Button>
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
