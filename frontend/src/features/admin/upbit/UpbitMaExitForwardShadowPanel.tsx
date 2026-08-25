"use client";

/**
 * Exit Forward Shadow — MA_DEAD_CROSS_CONFIRM2 vs REAL baseline.
 * 연구용 · REAL 미적용. READ ONLY.
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
import { dash, formatNumResearch, safeArray } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { DEFAULT_UPBIT_AUTOTRADING_UBA_ID } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";

type Props = {
  ubaId?: number;
};

export function UpbitMaExitForwardShadowPanel({
  ubaId = DEFAULT_UPBIT_AUTOTRADING_UBA_ID,
}: Props) {
  const summaryQ = useQuery({
    queryKey: queryKeys.admin.upbitResearchMaExitForwardShadowSummary(ubaId),
    queryFn: () => adminApi.getAdminUpbitResearchMaExitForwardShadowSummary(ubaId),
  });
  const rowsQ = useQuery({
    queryKey: queryKeys.admin.upbitResearchMaExitForwardShadowRows(ubaId),
    queryFn: () =>
      adminApi.getAdminUpbitResearchMaExitForwardShadowRows({
        uba_id: ubaId,
        page: 1,
        page_size: 100,
      }),
  });

  const summary = asRecord(summaryQ.data);
  const baseline = asRecord(summary?.baseline);
  const confirm2 = asRecord(summary?.confirm2);
  const cmp = asRecord(summary?.comparison);
  const early = asRecord(summary?.early_dump);
  const safety = asRecord(summary?.safety);
  const items = safeArray(asRecord(rowsQ.data)?.items);

  if (summaryQ.isLoading) {
    return (
      <Typography.Text type="secondary">Exit Forward Shadow 불러오는 중…</Typography.Text>
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

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="연구용 · REAL 미적용"
        description="REAL은 MA_DEAD_CROSS 즉시 청산 유지. Shadow는 Confirm2(2회 연속 dead cross)만 가상 평가합니다."
      />

      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="Sample N" value={Number(baseline?.sample_count ?? 0)} />
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {dash(summary?.sample_stage)}
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="Baseline Net"
              value={formatNumResearch(baseline?.net_pnl)}
              suffix="KRW"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              PF {dash(baseline?.profit_factor)} · WR{" "}
              {baseline?.win_rate != null
                ? `${(Number(baseline.win_rate) * 100).toFixed(0)}%`
                : "—"}
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="Confirm2 Net"
              value={formatNumResearch(confirm2?.net_pnl)}
              suffix="KRW"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              PF {dash(confirm2?.profit_factor)} · WR{" "}
              {confirm2?.win_rate != null
                ? `${(Number(confirm2.win_rate) * 100).toFixed(0)}%`
                : "—"}
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="Benefit (Net)"
              value={formatNumResearch(summary?.net_benefit)}
              suffix="KRW"
            />
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              Early dump {dash(early?.baseline)} → {dash(early?.confirm2)}
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]}>
        <Col xs={12} md={8}>
          <Card size="small" title="비교">
            <Typography.Text>
              Shadow better: {dash(cmp?.shadow_better_count)} · Baseline better:{" "}
              {dash(cmp?.baseline_better_count)} · Tie: {dash(cmp?.tie_count)}
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={12} md={8}>
          <Card size="small" title="Delay safety">
            <Typography.Text>
              Extra loss from delay: {dash(safety?.extra_loss_from_delay)} · SL
              delayed: {dash(safety?.stop_loss_delayed)} (must 0)
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={12} md={8}>
          <Card size="small" title="Rule">
            <Typography.Text>
              {dash(summary?.primary_shadow)} · {dash(summary?.rule_version)}
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      <Card size="small" title="상세 row">
        <Table
          size="small"
          rowKey={(r) => String(asRecord(r)?.shadow_row_id ?? "")}
          loading={rowsQ.isLoading}
          dataSource={items}
          pagination={false}
          columns={[
            { title: "Symbol", dataIndex: "symbol", render: dash },
            {
              title: "Entry",
              dataIndex: "entry_at",
              render: (v) => (v ? String(v).slice(0, 16) : "—"),
            },
            {
              title: "Baseline exit",
              render: (_, r) => {
                const row = asRecord(r);
                return `${dash(row?.baseline_exit_reason)} @ ${formatNumResearch(row?.baseline_net_pnl)}`;
              },
            },
            {
              title: "Shadow exit",
              render: (_, r) => {
                const row = asRecord(r);
                return `${dash(row?.shadow_exit_reason)} (${dash(row?.shadow_confirmation_count)}) @ ${formatNumResearch(row?.shadow_net_pnl)}`;
              },
            },
            {
              title: "Δ Net",
              dataIndex: "difference_net",
              render: (v) => formatNumResearch(v),
            },
            {
              title: "Status",
              dataIndex: "status",
              render: (v) => <Tag>{dash(v)}</Tag>,
            },
          ]}
        />
      </Card>
    </Space>
  );
}
