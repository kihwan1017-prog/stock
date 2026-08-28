"use client";

/**
 * Cross-market Shadow Research — No Trade But Learning 카드.
 * REAL vs Shadow 분리 표시 (READ ONLY).
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { DEFAULT_UPBIT_AUTOTRADING_UBA_ID } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";

type Props = {
  upbitUbaId?: number;
  kiwoomUbaId?: number;
};

function healthTag(health: string | undefined) {
  const h = (health || "UNKNOWN").toUpperCase();
  if (h === "HEALTHY") return <Tag color="green">정상 축적</Tag>;
  if (h === "LOW_SAMPLE") return <Tag color="gold">표본 부족</Tag>;
  if (h === "MATURATION_PENDING") return <Tag color="blue">성숙 대기</Tag>;
  if (h === "DATA_QUALITY_BLOCKED") return <Tag color="red">품질 차단</Tag>;
  return <Tag>{h}</Tag>;
}

function horizonLine(
  outcomes: Record<string, unknown> | null | undefined,
  key: string,
) {
  const h = asRecord(outcomes?.[key]);
  if (!h || Object.keys(h).length === 0) return "—";
  const matured = h.MATURED_N ?? 0;
  const pending = h.PENDING_N ?? 0;
  return `${matured} 성숙 / ${pending} 대기`;
}

export function CrossMarketShadowResearchPanel({
  upbitUbaId = DEFAULT_UPBIT_AUTOTRADING_UBA_ID,
  kiwoomUbaId = 1381,
}: Props) {
  const statusQ = useQuery({
    queryKey: queryKeys.admin.autotradingResearchStatus(
      upbitUbaId,
      kiwoomUbaId,
    ),
    queryFn: () =>
      adminApi.getAdminAutotradingResearchStatus({
        upbit_uba_id: upbitUbaId,
        kiwoom_uba_id: kiwoomUbaId,
      }),
  });

  if (statusQ.isLoading) {
    return (
      <Typography.Text type="secondary">
        Shadow 연구 현황 불러오는 중…
      </Typography.Text>
    );
  }
  if (statusQ.isError) {
    return (
      <Alert
        type="error"
        showIcon
        title="조회 실패"
        description={toApiError(statusQ.error).message}
      />
    );
  }

  const root = asRecord(statusQ.data);
  const upbit = asRecord(root?.UPBIT);
  const kiwoom = asRecord(root?.KIWOOM);
  const upbitSamples = asRecord(upbit?.samples);
  const e0Sem = asRecord(asRecord(upbit?.variant_semantics)?.E0);
  const e2Sem = asRecord(asRecord(upbit?.variant_semantics)?.E2);
  const horizonState = asRecord(upbit?.horizon_state);
  const e0Horizon = asRecord(horizonState?.E0);
  const upbitGrowth = asRecord(upbit?.growth);
  const kiwoomGrowth = asRecord(kiwoom?.growth);
  const upbitOutcomes = asRecord(upbit?.outcomes);
  const e0Out = asRecord(upbitOutcomes?.E0);
  const kiwoomOut = asRecord(kiwoom?.outcomes);
  const paired = asRecord(upbit?.paired_comparison);

  const upbitShadowAccumulating =
    Number(e0Sem?.NATURAL_OPPORTUNITY_POOL ?? 0) > 0 ||
    Number(upbitGrowth?.LAST_24H_NEW_SAMPLES ?? 0) > 0;
  const kiwoomShadowAccumulating =
    Number(kiwoom?.K0_SAMPLE ?? 0) > 0 ||
    Number(kiwoomGrowth?.LAST_24H_NEW_SAMPLES ?? 0) > 0;

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="전략 연구 / Shadow 검증"
        description="실주문·LIVE/ARM과 분리된 연구 표본입니다. Shadow 결과는 REAL 정책에 자동 반영되지 않습니다."
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card
            size="small"
            title="UPBIT — No Trade But Learning"
            extra={healthTag(String(upbit?.RESEARCH_HEALTH ?? ""))}
          >
            <Typography.Paragraph type="secondary">
              자연기회·PASS 연구표본·REAL 매매는 별개입니다. Shadow는 주문을
              만들지 않습니다.
            </Typography.Paragraph>
            <Row gutter={12}>
              <Col span={12}>
                <Statistic
                  title="전체 자연기회 (E0)"
                  value={Number(e0Sem?.NATURAL_OPPORTUNITY_POOL ?? 0)}
                />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  distinct selection_id
                </Typography.Text>
              </Col>
              <Col span={12}>
                <Statistic
                  title="PASS 연구표본 (E0)"
                  value={Number(e0Sem?.PASS_SAMPLE ?? 0)}
                />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  VALID {Number(e0Sem?.VALID_PASS_SAMPLE ?? 0)}
                </Typography.Text>
              </Col>
            </Row>
            <Row gutter={12} style={{ marginTop: 8 }}>
              <Col span={12}>
                <Statistic
                  title="PASS 연구표본 (E2)"
                  value={Number(e2Sem?.PASS_SAMPLE ?? 0)}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="4h / 24h 완료 (E0 PASS)"
                  value={`${Number(e0Sem?.MATURED_PASS_4H ?? 0)} / ${Number(e0Sem?.MATURED_PASS_24H ?? 0)}`}
                />
              </Col>
            </Row>
            <Typography.Paragraph style={{ marginTop: 12, marginBottom: 4 }}>
              오늘 자연기회 증가: 1h +
              {Number(upbitGrowth?.LAST_1H_NEW_SAMPLES ?? 0)} · 24h +
              {Number(upbitGrowth?.LAST_24H_NEW_SAMPLES ?? 0)}
            </Typography.Paragraph>
            <Typography.Paragraph style={{ marginBottom: 4 }}>
              4h: {horizonLine(asRecord(e0Horizon), "4H")} · 24h:{" "}
              {horizonLine(asRecord(e0Horizon), "24H")}
            </Typography.Paragraph>
            <Typography.Paragraph style={{ marginBottom: 4 }}>
              E0↔E2 평가됨 {Number(paired?.PAIRED_EVALUATED_N ?? 0)} · 양쪽
              PASS {Number(paired?.PAIRED_PASS_N ?? 0)} · E0 PASS only{" "}
              {Number(paired?.E0_PASS_ONLY_N ?? 0)} · E2 PASS only{" "}
              {Number(paired?.E2_PASS_ONLY_N ?? 0)}
            </Typography.Paragraph>
            <Tag color={upbit?.RESEARCH_REVIEW_READY ? "green" : "default"}>
              Review Ready: {upbit?.RESEARCH_REVIEW_READY ? "예" : "아니오"}
            </Tag>{" "}
            <Tag>REAL promotion: 금지</Tag>
            <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
              {upbitShadowAccumulating
                ? "실제 거래 없음 — 연구 표본은 정상 축적 중"
                : "실제 거래 없음 — Shadow 표본 수집 대기"}
            </Typography.Paragraph>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card
            size="small"
            title="KIWOOM — No Trade But Learning"
            extra={healthTag(String(kiwoom?.RESEARCH_HEALTH ?? ""))}
          >
            <Typography.Paragraph type="secondary">
              Golden Cross(K0) — REAL 주문과 독립. GC 없으면 0이 정상입니다.
            </Typography.Paragraph>
            <Row gutter={12}>
              <Col span={12}>
                <Statistic
                  title="K0 opportunities"
                  value={Number(kiwoom?.K0_SAMPLE ?? 0)}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="K0 VALID"
                  value={Number(kiwoom?.K0_VALID_SAMPLE ?? 0)}
                />
              </Col>
            </Row>
            <Typography.Paragraph style={{ marginTop: 12, marginBottom: 4 }}>
              오늘 증가: 1h +{Number(kiwoomGrowth?.LAST_1H_NEW_SAMPLES ?? 0)} ·
              24h +{Number(kiwoomGrowth?.LAST_24H_NEW_SAMPLES ?? 0)}
            </Typography.Paragraph>
            <Typography.Paragraph style={{ marginBottom: 4 }}>
              24h outcome: {horizonLine(kiwoomOut, "24H")}
            </Typography.Paragraph>
            {kiwoom?.KIWOOM_24H_SEMANTICS ? (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                24h: {String(kiwoom.KIWOOM_24H_SEMANTICS)} — KRX 비거래시간은
                MISSING_DATA
              </Typography.Paragraph>
            ) : null}
            <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
              {kiwoomShadowAccumulating
                ? "Golden Cross 연구 표본 축적 중"
                : "실제 거래 없음 — Golden Cross 기회 아직 없음 (정상)"}
            </Typography.Paragraph>
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
