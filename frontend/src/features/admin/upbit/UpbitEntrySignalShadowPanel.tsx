"use client";

/**
 * Entry Signal Shadow — E0~E4 PORTFOLIO_BULLISH research.
 * REAL 정책 미변경 · READ ONLY.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import {
  dash,
  formatNumResearch,
  safeArray,
} from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { DEFAULT_UPBIT_AUTOTRADING_UBA_ID } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";

type Props = {
  ubaId?: number;
};

const VARIANT_ORDER = ["E0", "E1", "E2", "E3", "E4"] as const;

export function UpbitEntrySignalShadowPanel({
  ubaId = DEFAULT_UPBIT_AUTOTRADING_UBA_ID,
}: Props) {
  const summaryQ = useQuery({
    queryKey: queryKeys.admin.upbitResearchEntrySignalShadowSummary(ubaId),
    queryFn: () =>
      adminApi.getAdminUpbitResearchEntrySignalShadowSummary(ubaId),
  });
  const rowsQ = useQuery({
    queryKey: queryKeys.admin.upbitResearchEntrySignalShadowRows(ubaId),
    queryFn: () =>
      adminApi.getAdminUpbitResearchEntrySignalShadowRows({
        uba_id: ubaId,
        limit: 50,
      }),
  });

  const summary = asRecord(summaryQ.data);
  const variants = asRecord(summary?.variants);
  const blocks = asRecord(summary?.block_reasons);
  const forward = asRecord(summary?.forward);
  const replay = asRecord(summary?.replay);
  const replayVariants = asRecord(replay?.variants);
  const rows = safeArray(asRecord(rowsQ.data)?.rows);

  if (summaryQ.isLoading) {
    return (
      <Typography.Text type="secondary">
        Entry Signal Shadow 불러오는 중…
      </Typography.Text>
    );
  }
  if (summaryQ.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(summaryQ.error).message}
      />
    );
  }

  const variantRows = VARIANT_ORDER.map((code) => {
    const v = asRecord(variants?.[code]) || asRecord(replayVariants?.[code]) || {};
    return {
      key: code,
      variant: code,
      description: String(v.description ?? dash),
      samples: v.SAMPLES ?? v.samples ?? 0,
      entries: v.ENTRIES ?? v.entries ?? 0,
      entry_rate: v.ENTRY_RATE ?? v.entry_rate,
      win_rate: v.WIN_RATE ?? v.win_rate,
      net: v.NET_AVG_15M ?? v.NET,
      mfe: v.AVG_MFE,
      mae: v.AVG_MAE,
      status: String(v.STATUS ?? "REPLAY"),
    };
  });

  const blockRows = Object.entries(blocks || {}).map(([reason, n]) => ({
    key: reason,
    reason,
    count: n,
  }));

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="연구용 · REAL 매수 조건 미변경"
        description={
          <span>
            현재 실제 매수 조건: <Tag color="blue">E0</Tag> 유지.
            연구 중: E1 단기MA · E2 MA간격 · E3 RSI · E4 Signal Suppression.
            REAL 적용: <Tag>없음</Tag>
          </span>
        }
      />

      <Row gutter={12}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="Forward samples"
              value={Number(forward?.FORWARD_SAMPLE_COUNT ?? 0)}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="Completed"
              value={Number(forward?.COMPLETED_COUNT ?? 0)}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="Target"
              value={Number(forward?.TARGET ?? 100)}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="Replay obs"
              value={Number(replay?.observations ?? 0)}
            />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="E0–E4 variants">
        <Table
          size="small"
          pagination={false}
          dataSource={variantRows}
          columns={[
            { title: "Variant", dataIndex: "variant", width: 70 },
            { title: "설명", dataIndex: "description", ellipsis: true },
            { title: "Samples", dataIndex: "samples", width: 80 },
            { title: "Entries", dataIndex: "entries", width: 80 },
            {
              title: "Entry%",
              dataIndex: "entry_rate",
              width: 80,
              render: (v) => formatNumResearch(v, 2),
            },
            {
              title: "Win%",
              dataIndex: "win_rate",
              width: 80,
              render: (v) => formatNumResearch(v, 2),
            },
            {
              title: "Net15m",
              dataIndex: "net",
              width: 90,
              render: (v) => formatNumResearch(v, 3),
            },
            {
              title: "MFE",
              dataIndex: "mfe",
              width: 80,
              render: (v) => formatNumResearch(v, 3),
            },
            {
              title: "MAE",
              dataIndex: "mae",
              width: 80,
              render: (v) => formatNumResearch(v, 3),
            },
            {
              title: "REAL",
              dataIndex: "variant",
              width: 70,
              render: (v) =>
                v === "E0" ? <Tag color="green">baseline</Tag> : <Tag>연구</Tag>,
            },
          ]}
        />
      </Card>

      <Card size="small" title="진입 차단 원인 (Forward E0)">
        <Table
          size="small"
          pagination={false}
          dataSource={blockRows}
          columns={[
            { title: "Reason", dataIndex: "reason" },
            { title: "Count", dataIndex: "count", width: 100 },
          ]}
          locale={{ emptyText: "아직 Forward 표본 없음 — Replay 결과 참고" }}
        />
      </Card>

      <Card size="small" title="최근 shadow rows">
        <Table
          size="small"
          pagination={{ pageSize: 10 }}
          dataSource={rows.map((r, i) => ({
            key: String(asRecord(r)?.shadow_id ?? i),
            ...asRecord(r),
          }))}
          columns={[
            { title: "Symbol", dataIndex: "symbol", width: 110 },
            { title: "Variant", dataIndex: "variant", width: 70 },
            { title: "Baseline", dataIndex: "baseline_decision", width: 90 },
            {
              title: "Block",
              dataIndex: "baseline_block_reason",
              ellipsis: true,
            },
            { title: "Shadow", dataIndex: "shadow_decision", width: 90 },
            { title: "Outcome", dataIndex: "outcome_status", width: 110 },
          ]}
        />
      </Card>
    </Space>
  );
}
