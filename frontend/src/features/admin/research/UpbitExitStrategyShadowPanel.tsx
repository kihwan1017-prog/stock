"use client";

/**
 * Exit 전략 Shadow 비교 — RESEARCH ONLY.
 * REAL SL/TP/Trailing/Time 활성화 버튼 없음.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";

import * as adminApi from "@/features/admin/api/adminApi";
import { formatNumResearch } from "@/features/admin/upbit/researchDetailFormat";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type VariantRow = {
  key: string;
  strategy_family: string;
  variant_code: string;
  n: number;
  checkpoint: string;
  net_pnl: number | null;
  profit_factor: number | null;
  win_rate: number | null;
  avg_hold_min: number | null;
  max_drawdown: number | null;
  vs_ma_net_delta: number | null;
  readiness: string;
};

export function UpbitExitStrategyShadowPanel({
  ubaId = 1380,
}: {
  ubaId?: number;
}) {
  const q = useQuery({
    queryKey: queryKeys.admin.upbitResearchExitStrategyShadowSummary(ubaId),
    queryFn: () =>
      adminApi.getAdminUpbitResearchExitStrategyShadowSummary(ubaId),
    refetchInterval: 60_000,
  });

  if (q.isLoading) {
    return (
      <Typography.Text type="secondary">
        Exit 전략 Shadow 불러오는 중…
      </Typography.Text>
    );
  }
  if (q.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(q.error).message}
      />
    );
  }

  const data = asRecord(q.data);
  if (!data?.ok) {
    return (
      <Alert
        type="warning"
        showIcon
        title="요약 없음"
        description="API ok=false 또는 데이터 없음"
      />
    );
  }

  const baseline = asRecord(data.real_baseline);
  const sched = asRecord(data.scheduler);
  const bestNet = asRecord(data.best_net_variant);
  const bestPf = asRecord(data.best_pf_variant);
  const variantsRaw = Array.isArray(data.variants) ? data.variants : [];

  const rows: VariantRow[] = variantsRaw.map((v, i) => {
    const r = asRecord(v) ?? {};
    return {
      key: `${String(r.strategy_family)}-${String(r.variant_code)}-${i}`,
      strategy_family: String(r.strategy_family ?? ""),
      variant_code: String(r.variant_code ?? ""),
      n: Number(r.n ?? 0),
      checkpoint: String(r.checkpoint ?? "INSUFFICIENT"),
      net_pnl: r.net_pnl == null ? null : Number(r.net_pnl),
      profit_factor: r.profit_factor == null ? null : Number(r.profit_factor),
      win_rate: r.win_rate == null ? null : Number(r.win_rate),
      avg_hold_min: r.avg_hold_min == null ? null : Number(r.avg_hold_min),
      max_drawdown: r.max_drawdown == null ? null : Number(r.max_drawdown),
      vs_ma_net_delta:
        r.vs_ma_net_delta == null ? null : Number(r.vs_ma_net_delta),
      readiness: String(r.readiness ?? "NOT_READY"),
    };
  });

  const columns: ColumnsType<VariantRow> = [
    { title: "Family", dataIndex: "strategy_family", width: 120 },
    { title: "Variant", dataIndex: "variant_code", width: 120 },
    {
      title: "N / 300",
      key: "nbar",
      width: 140,
      render: (_, r) => (
        <Space orientation="vertical" size={0} style={{ width: "100%" }}>
          <Typography.Text>
            {r.n} / 300 · {r.checkpoint}
          </Typography.Text>
          <Progress
            percent={Math.min(100, Math.round((r.n / 300) * 100))}
            size="small"
            showInfo={false}
          />
        </Space>
      ),
    },
    {
      title: "Net",
      dataIndex: "net_pnl",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "PF",
      dataIndex: "profit_factor",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "승률",
      dataIndex: "win_rate",
      render: (v) =>
        v == null || !Number.isFinite(Number(v))
          ? "—"
          : `${(Number(v) * 100).toFixed(1)}%`,
    },
    {
      title: "평균보유(분)",
      dataIndex: "avg_hold_min",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "MDD",
      dataIndex: "max_drawdown",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "vs MA",
      dataIndex: "vs_ma_net_delta",
      render: (v) => formatNumResearch(v),
    },
    {
      title: "상태",
      dataIndex: "readiness",
      render: (v) => (
        <Tag color={v === "READY_FOR_REVIEW" ? "blue" : "default"}>
          {String(v)}
        </Tag>
      ),
    },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="Exit 전략 Shadow (연구 전용)"
        description="REAL 매도 정책은 변경되지 않습니다. Shadow 결과가 좋아도 자동 승격하지 않습니다."
      />

      <Card size="small" title="현재 REAL Exit">
        <Space wrap>
          <Tag color="green">
            MA_DEAD_CROSS={String(baseline?.MA_DEAD_CROSS ?? "—")}
          </Tag>
          <Tag>SL={String(baseline?.STOP_LOSS ?? "—")}</Tag>
          <Tag>TP={String(baseline?.TAKE_PROFIT ?? "—")}</Tag>
          <Tag>Trailing={String(baseline?.TRAILING ?? "—")}</Tag>
          <Tag>Time={String(baseline?.TIME_EXIT ?? "—")}</Tag>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Statistic
            title="Natural Entries"
            value={Number(data.natural_entries ?? 0)}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="Active Experiments"
            value={Number(data.active_experiments ?? 0)}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="Matured Samples"
            value={Number(data.matured_or_triggered ?? 0)}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="Scheduler"
            value={sched?.enabled ? "ON" : "OFF"}
          />
        </Col>
      </Row>

      {(bestNet || bestPf) && (
        <Alert
          type="success"
          showIcon
          title="현재 최고 (연구 라벨)"
          description={`Best Net: ${String(bestNet?.variant_code ?? "—")} · Best PF: ${String(bestPf?.variant_code ?? "—")} · AUTO_PROMOTE=false`}
        />
      )}

      {rows.length === 0 ? (
        <EmptyHint />
      ) : (
        <Table
          size="small"
          rowKey="key"
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 20 }}
          scroll={{ x: 960 }}
        />
      )}
    </Space>
  );
}

function EmptyHint() {
  return (
    <Alert
      type="warning"
      showIcon
      title="아직 Forward sample 없음"
      description="자연 REAL AUTO BUY가 발생하면 자동으로 Shadow experiment가 생성됩니다. 강제 sample/synthetic 주입 없음."
    />
  );
}
