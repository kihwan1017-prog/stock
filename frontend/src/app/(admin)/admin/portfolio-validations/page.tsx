"use client";

/**
 * STEP 12-13 — Portfolio Validation(관리자 전용).
 * 이미 승인된 복수의 Strategy Definition과 이미 완료된 Backtest 결과만
 * 조합해 상관관계/집중도/분산효과/위험기여도/중복노출을 평가한다. 이
 * 화면에서 새 Backtest를 실행하거나 실제 Portfolio/자금을 배분하지
 * 않는다 — Weight도 자동 최적화하지 않는다(직접 입력 또는 균등배분만
 * 지원).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Divider,
  Empty,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const { Text, Paragraph } = Typography;

const STATUS_COLOR: Record<string, string> = {
  DIVERSIFIED: "success",
  ACCEPTABLE: "processing",
  CONCENTRATED: "warning",
  HIGHLY_CORRELATED: "warning",
  HIGH_RISK: "error",
  INSUFFICIENT_DATA: "default",
};

const SEVERITY_COLOR: Record<string, string> = {
  HIGH: "error",
  WARNING: "warning",
  INFO: "default",
};

interface StrategyRow {
  key: number;
  strategyDefinitionId: number | null;
  backtestRunId: number | null;
  customWeight: number | null;
}

let nextRowKey = 1;

function newRow(): StrategyRow {
  return {
    key: nextRowKey++,
    strategyDefinitionId: null,
    backtestRunId: null,
    customWeight: null,
  };
}

export default function AdminPortfolioValidationsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [rows, setRows] = useState<StrategyRow[]>([newRow(), newRow()]);
  const [weightingMethod, setWeightingMethod] = useState<"EQUAL_WEIGHT" | "CUSTOM_WEIGHT">(
    "EQUAL_WEIGHT",
  );
  const [alignmentPolicy, setAlignmentPolicy] = useState<"INTERSECTION" | "UNION_FORWARD_FILL">(
    "INTERSECTION",
  );
  const [minimumOverlapDays, setMinimumOverlapDays] = useState<number>(60);
  const [initialCapital, setInitialCapital] = useState<number>(10_000_000);
  const [reportId, setReportId] = useState<number | null>(null);

  const recentRunsQuery = useQuery({
    queryKey: ["admin", "portfolio-validation", "recent-backtest-runs"],
    queryFn: () => adminApi.listBacktestRuns({ limit: 30 }),
  });
  const recentRuns = extractRows(recentRunsQuery.data);

  const addRow = () => {
    if (rows.length >= 10) return;
    setRows((prev) => [...prev, newRow()]);
  };
  const removeRow = (key: number) => {
    if (rows.length <= 2) return;
    setRows((prev) => prev.filter((r) => r.key !== key));
  };
  const updateRow = (key: number, patch: Partial<StrategyRow>) => {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  };

  const runMutation = useMutation({
    mutationFn: () => {
      const strategyDefinitionIds = rows.map((r) => r.strategyDefinitionId as number);
      const backtestRunIds = rows.map((r) => r.backtestRunId as number);
      const body: Parameters<typeof adminApi.runPortfolioValidation>[0] = {
        strategy_definition_ids: strategyDefinitionIds,
        backtest_run_ids: backtestRunIds,
        weighting_method: weightingMethod,
        alignment_policy: alignmentPolicy,
        minimum_overlap_days: minimumOverlapDays,
        initial_capital: String(initialCapital),
      };
      if (weightingMethod === "CUSTOM_WEIGHT") {
        const weights: Record<number, string> = {};
        for (const r of rows) {
          if (r.strategyDefinitionId != null) {
            weights[r.strategyDefinitionId] = String(r.customWeight ?? 0);
          }
        }
        body.strategy_weights = weights;
      }
      return adminApi.runPortfolioValidation(body);
    },
    onSuccess: (data) => {
      const id = asRecord(data)?.report_id as number | undefined;
      if (id != null) {
        setReportId(id);
        message.success("Portfolio Validation이 완료되었습니다.");
        queryClient.invalidateQueries({ queryKey: queryKeys.admin.portfolioValidation(id) });
      }
    },
    onError: (error) => {
      message.error(toApiError(error).message);
    },
  });

  const reportQuery = useQuery({
    queryKey: queryKeys.admin.portfolioValidation(reportId ?? 0),
    queryFn: () => adminApi.getPortfolioValidation(reportId as number),
    enabled: reportId != null,
  });
  const report = asRecord(reportQuery.data);

  const rowsValid =
    rows.length >= 2 &&
    rows.length <= 10 &&
    rows.every((r) => r.strategyDefinitionId != null && r.backtestRunId != null);

  const correlationPayload = asRecord(report?.correlation_payload);
  const correlationMatrix = asRecord(correlationPayload?.matrix);
  const highlyCorrelatedPairs = extractRows(correlationPayload?.highly_correlated_pairs);
  const concentration = asRecord(report?.concentration_payload);
  const diversification = asRecord(report?.diversification_payload);
  const riskContribution = asRecord(report?.risk_contribution_payload);
  const riskContributions = extractRows(riskContribution?.contributions);
  const duplicateExposures = extractRows(report?.duplicate_exposure_payload);
  const portfolioKpi = asRecord(report?.portfolio_kpi_payload);
  const portfolioEquity = extractRows(report?.portfolio_equity_payload);
  const strategyIds: number[] = Array.isArray(report?.strategy_definition_ids)
    ? (report?.strategy_definition_ids as number[])
    : [];

  return (
    <AdminPageShell
      title="Portfolio Validation"
      description="이미 승인된 복수 Strategy Definition의 기존 Backtest 결과만 조합해 상관관계·집중도·분산효과·위험기여도·중복노출을 검증합니다. 새 Backtest 실행이나 실제 자금 배분은 발생하지 않습니다."
    >
      <Card title="Strategy 구성 (2~10개)" style={{ marginBottom: 16 }}>
        <Space orientation="vertical" style={{ width: "100%" }} size="middle">
          {rows.map((row, idx) => (
            <Space key={row.key} wrap>
              <Text type="secondary">#{idx + 1}</Text>
              <InputNumber
                placeholder="Strategy Definition ID"
                value={row.strategyDefinitionId}
                onChange={(v) => updateRow(row.key, { strategyDefinitionId: v })}
                style={{ width: 180 }}
              />
              <InputNumber
                placeholder="Backtest Run ID"
                value={row.backtestRunId}
                onChange={(v) => updateRow(row.key, { backtestRunId: v })}
                style={{ width: 160 }}
              />
              {weightingMethod === "CUSTOM_WEIGHT" && (
                <InputNumber
                  placeholder="Weight(0~1)"
                  min={0}
                  max={1}
                  step={0.01}
                  value={row.customWeight}
                  onChange={(v) => updateRow(row.key, { customWeight: v })}
                  style={{ width: 140 }}
                />
              )}
              <Button danger disabled={rows.length <= 2} onClick={() => removeRow(row.key)}>
                제거
              </Button>
            </Space>
          ))}
          <Button onClick={addRow} disabled={rows.length >= 10}>
            + Strategy 추가
          </Button>

          <Divider style={{ margin: "8px 0" }} />

          <Space wrap size="middle">
            <Space orientation="vertical" size={0}>
              <Text type="secondary">Weighting Method</Text>
              <Select
                value={weightingMethod}
                onChange={(v) => setWeightingMethod(v)}
                style={{ width: 180 }}
                options={[
                  { value: "EQUAL_WEIGHT", label: "EQUAL_WEIGHT(균등배분)" },
                  { value: "CUSTOM_WEIGHT", label: "CUSTOM_WEIGHT(직접입력)" },
                ]}
              />
            </Space>
            <Space orientation="vertical" size={0}>
              <Text type="secondary">Alignment Policy</Text>
              <Select
                value={alignmentPolicy}
                onChange={(v) => setAlignmentPolicy(v)}
                style={{ width: 200 }}
                options={[
                  { value: "INTERSECTION", label: "INTERSECTION(공통기간)" },
                  {
                    value: "UNION_FORWARD_FILL",
                    label: "UNION_FORWARD_FILL(미지원)",
                  },
                ]}
              />
            </Space>
            <Space orientation="vertical" size={0}>
              <Text type="secondary">최소 공통기간(일)</Text>
              <InputNumber
                value={minimumOverlapDays}
                min={1}
                onChange={(v) => setMinimumOverlapDays(v ?? 60)}
              />
            </Space>
            <Space orientation="vertical" size={0}>
              <Text type="secondary">Initial Capital</Text>
              <InputNumber
                value={initialCapital}
                min={1}
                step={1_000_000}
                style={{ width: 160 }}
                onChange={(v) => setInitialCapital(v ?? 10_000_000)}
              />
            </Space>
          </Space>

          {alignmentPolicy === "UNION_FORWARD_FILL" && (
            <Alert
              type="warning"
              showIcon
              title="UNION_FORWARD_FILL은 이번 STEP에서 지원하지 않아 실행 시 오류로 차단됩니다(경계 조건 미확정으로 명시적 차단)."
            />
          )}

          <Button
            type="primary"
            loading={runMutation.isPending}
            disabled={!rowsValid || runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            Portfolio Validation 실행
          </Button>
        </Space>
      </Card>

      <Card title="참고: 최근 Backtest Run 목록" style={{ marginBottom: 16 }}>
        <Table
          size="small"
          rowKey={(r) => cell(r.backtest_run_id)}
          dataSource={recentRuns}
          loading={recentRunsQuery.isLoading}
          pagination={{ pageSize: 5 }}
          columns={[
            { title: "Backtest Run ID", dataIndex: "backtest_run_id", render: cell },
            {
              title: "Strategy Definition ID",
              dataIndex: "strategy_definition_id",
              render: cell,
            },
            { title: "종목", dataIndex: "symbol", render: cell },
            { title: "상태", dataIndex: "status_code", render: cell },
            { title: "시작일", dataIndex: "start_date", render: cell },
            { title: "종료일", dataIndex: "end_date", render: cell },
          ]}
        />
      </Card>

      {reportId != null && (
        <Card
          title={`Validation Report #${reportId}`}
          loading={reportQuery.isLoading}
        >
          {report == null ? (
            <Empty description="결과 없음" />
          ) : (
            <Space orientation="vertical" style={{ width: "100%" }} size="large">
              <Space wrap>
                <Tag color={STATUS_COLOR[cell(report.validation_status)] ?? "default"}>
                  {cell(report.validation_status)}
                </Tag>
                <Text>Robustness Score: {cell(report.robustness_score)}</Text>
                <Text>Strategy 수: {cell(report.strategy_count)}</Text>
                <Text>공통 관측 수: {cell(report.observation_count)}</Text>
                <Text type="secondary">Algorithm Version: {cell(report.algorithm_version)}</Text>
              </Space>

              <Alert
                type="info"
                showIcon
                title={cell(report.methodology_note)}
              />

              <Descriptions title="Portfolio KPI" bordered size="small" column={3}>
                <Descriptions.Item label="Total Return(%)">
                  {cell(portfolioKpi?.total_return)}
                </Descriptions.Item>
                <Descriptions.Item label="CAGR(%)">{cell(portfolioKpi?.cagr)}</Descriptions.Item>
                <Descriptions.Item label="Sharpe">
                  {cell(portfolioKpi?.sharpe_ratio)}
                </Descriptions.Item>
                <Descriptions.Item label="Sortino">
                  {cell(portfolioKpi?.sortino_ratio)}
                </Descriptions.Item>
                <Descriptions.Item label="Calmar">
                  {cell(portfolioKpi?.calmar_ratio)}
                </Descriptions.Item>
                <Descriptions.Item label="MDD(%)">
                  {cell(portfolioKpi?.maximum_drawdown_percent)}
                </Descriptions.Item>
                <Descriptions.Item label="Ulcer Index">
                  {cell(portfolioKpi?.ulcer_index)}
                </Descriptions.Item>
                <Descriptions.Item label="Volatility(%)">
                  {cell(portfolioKpi?.volatility)}
                </Descriptions.Item>
                <Descriptions.Item label="관측 수">
                  {cell(portfolioKpi?.observation_count)}
                </Descriptions.Item>
              </Descriptions>

              <div>
                <Typography.Title level={5}>Correlation Matrix</Typography.Title>
                <Table
                  size="small"
                  rowKey={(r) => cell(r.id)}
                  pagination={false}
                  dataSource={strategyIds.map((a) => ({
                    id: a,
                    ...Object.fromEntries(
                      strategyIds.map((b) => [
                        String(b),
                        cell(asRecord(correlationMatrix?.[String(a)])?.[String(b)]),
                      ]),
                    ),
                  }))}
                  columns={[
                    { title: "전략", dataIndex: "id", render: cell },
                    ...strategyIds.map((b) => ({
                      title: `#${b}`,
                      dataIndex: String(b),
                    })),
                  ]}
                />
                <Paragraph type="secondary" style={{ marginTop: 8 }}>
                  평균 상관관계: {cell(correlationPayload?.average_pairwise_correlation)} / 최대
                  상관관계: {cell(correlationPayload?.maximum_pairwise_correlation)}
                </Paragraph>
                {highlyCorrelatedPairs.length > 0 && (
                  <Table
                    size="small"
                    rowKey={(r) => `${cell(r.strategy_a)}-${cell(r.strategy_b)}`}
                    dataSource={highlyCorrelatedPairs}
                    pagination={false}
                    columns={[
                      { title: "Strategy A", dataIndex: "strategy_a", render: cell },
                      { title: "Strategy B", dataIndex: "strategy_b", render: cell },
                      { title: "Correlation", dataIndex: "correlation", render: cell },
                    ]}
                  />
                )}
              </div>

              <Descriptions title="Concentration Analysis" bordered size="small" column={2}>
                <Descriptions.Item label="Status">
                  {cell(concentration?.concentration_status)}
                </Descriptions.Item>
                <Descriptions.Item label="HHI">
                  {cell(concentration?.herfindahl_hirschman_index)}
                </Descriptions.Item>
                <Descriptions.Item label="최대 비중">
                  {cell(concentration?.largest_strategy_weight)}
                </Descriptions.Item>
                <Descriptions.Item label="Top2 합계">
                  {cell(concentration?.top2_weight_sum)}
                </Descriptions.Item>
                <Descriptions.Item label="유효 전략 수">
                  {cell(concentration?.effective_number_of_strategies)}
                </Descriptions.Item>
              </Descriptions>

              <div>
                <Typography.Title level={5}>Risk Contribution</Typography.Title>
                <Table
                  size="small"
                  rowKey={(r) => cell(r.strategy_definition_id)}
                  dataSource={riskContributions}
                  pagination={false}
                  columns={[
                    { title: "전략", dataIndex: "strategy_definition_id", render: cell },
                    { title: "Weight", dataIndex: "weight", render: cell },
                    { title: "Volatility", dataIndex: "volatility", render: cell },
                    {
                      title: "Risk Contribution(%)",
                      dataIndex: "risk_contribution_percent",
                      render: cell,
                    },
                  ]}
                />
                <Paragraph type="secondary" style={{ marginTop: 8 }}>
                  Portfolio Variance: {cell(riskContribution?.portfolio_variance)} / 합계:{" "}
                  {cell(riskContribution?.total_risk_contribution_percent)}%
                </Paragraph>
              </div>

              <Descriptions title="Diversification Benefit" bordered size="small" column={2}>
                <Descriptions.Item label="Diversification Benefit">
                  {cell(diversification?.diversification_benefit)}
                </Descriptions.Item>
                <Descriptions.Item label="Portfolio Volatility(%)">
                  {cell(diversification?.portfolio_volatility)}
                </Descriptions.Item>
                <Descriptions.Item label="가중평균 Standalone MDD(%)">
                  {cell(diversification?.weighted_average_standalone_maximum_drawdown)}
                </Descriptions.Item>
                <Descriptions.Item label="Portfolio MDD(%)">
                  {cell(diversification?.portfolio_maximum_drawdown)}
                </Descriptions.Item>
                <Descriptions.Item label="MDD 감소분">
                  {cell(diversification?.maximum_drawdown_reduction)}
                </Descriptions.Item>
              </Descriptions>

              <div>
                <Typography.Title level={5}>Duplicate Exposure Detection</Typography.Title>
                {duplicateExposures.length === 0 ? (
                  <Empty description="탐지된 중복 노출 없음" />
                ) : (
                  <Table
                    size="small"
                    rowKey={(r) => `${cell(r.strategy_a)}-${cell(r.strategy_b)}`}
                    dataSource={duplicateExposures}
                    pagination={false}
                    columns={[
                      { title: "Strategy A", dataIndex: "strategy_a", render: cell },
                      { title: "Strategy B", dataIndex: "strategy_b", render: cell },
                      {
                        title: "Severity",
                        dataIndex: "severity",
                        render: (v: string) => (
                          <Tag color={SEVERITY_COLOR[v] ?? "default"}>{v}</Tag>
                        ),
                      },
                      {
                        title: "Reasons",
                        dataIndex: "reasons",
                        render: (v: string[]) => v?.join(", "),
                      },
                    ]}
                  />
                )}
              </div>

              <div>
                <Typography.Title level={5}>
                  Portfolio Equity Curve({portfolioEquity.length}개 관측)
                </Typography.Title>
                <Table
                  size="small"
                  rowKey={(r) => cell(r.trade_date)}
                  dataSource={portfolioEquity}
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: "날짜", dataIndex: "trade_date", render: cell },
                    { title: "Equity", dataIndex: "equity_value", render: cell },
                  ]}
                />
              </div>

              <Descriptions title="Provenance" bordered size="small" column={1}>
                <Descriptions.Item label="Report Input Hash">
                  <Text code>{cell(report.report_input_hash)}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="공통 기간">
                  {cell(report.common_start_date)} ~ {cell(report.common_end_date)}
                </Descriptions.Item>
              </Descriptions>
            </Space>
          )}
        </Card>
      )}
    </AdminPageShell>
  );
}
