"use client";

/**
 * AutoTrading Process Version + Visual Map + Trace
 * OBSERVABILITY ONLY — REAL policy 변경 없음
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Row,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord } from "@/shared/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { DEFAULT_UPBIT_AUTOTRADING_UBA_ID } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";

const { Text, Title, Paragraph } = Typography;

function statusColor(status: string | undefined): string {
  const s = String(status || "UNKNOWN").toUpperCase();
  if (s === "OK" || s === "PASS" || s === "FILL") return "success";
  if (s === "WAIT") return "warning";
  if (s === "ERROR" || s === "BLOCK") return "error";
  if (s === "UNREACHED") return "default";
  return "processing";
}

function statusLabel(status: string | undefined): string {
  const s = String(status || "UNKNOWN").toUpperCase();
  if (s === "OK") return "정상";
  if (s === "WAIT") return "대기";
  if (s === "ERROR") return "장애";
  if (s === "BLOCK") return "차단";
  if (s === "UNREACHED") return "미도달";
  return s;
}

export function AutoTradingProcessMapPanel() {
  const [market, setMarket] = useState<"UPBIT" | "KIWOOM">("UPBIT");
  const [techDetail, setTechDetail] = useState(false);
  const [selectedNode, setSelectedNode] = useState<Record<string, unknown> | null>(
    null,
  );
  const [selectedTraceId, setSelectedTraceId] = useState<number | null>(null);
  const qc = useQueryClient();
  const ubaId =
    market === "UPBIT" ? DEFAULT_UPBIT_AUTOTRADING_UBA_ID : 1381;

  const currentQ = useQuery({
    queryKey: queryKeys.admin.autotradingProcessCurrent(market, ubaId),
    queryFn: () => adminApi.getAdminAutotradingProcessCurrent(market, ubaId),
  });
  const changesQ = useQuery({
    queryKey: queryKeys.admin.autotradingProcessChanges(market),
    queryFn: () => adminApi.getAdminAutotradingProcessChanges(market),
  });
  const tracesQ = useQuery({
    queryKey: queryKeys.admin.autotradingTraces(market),
    queryFn: () => adminApi.getAdminAutotradingTraces(market, 50),
  });
  const versionsQ = useQuery({
    queryKey: queryKeys.admin.autotradingProcessVersions(market),
    queryFn: () => adminApi.getAdminAutotradingProcessVersions(market),
  });
  const traceDetailQ = useQuery({
    queryKey: queryKeys.admin.autotradingTrace(selectedTraceId ?? 0),
    queryFn: () => adminApi.getAdminAutotradingTrace(selectedTraceId!),
    enabled: selectedTraceId != null && selectedTraceId > 0,
  });

  const bootstrapM = useMutation({
    mutationFn: () => adminApi.postAdminAutotradingProcessBootstrap(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "autotrading-process-current"] });
      void qc.invalidateQueries({ queryKey: ["admin", "autotrading-traces"] });
      void qc.invalidateQueries({ queryKey: ["admin", "autotrading-process-changes"] });
      void qc.invalidateQueries({ queryKey: ["admin", "autotrading-process-versions"] });
    },
  });

  const current = asRecord(currentQ.data);
  const pv = asRecord(current?.process_version);
  const nodes = useMemo(() => {
    const raw = current?.nodes;
    return Array.isArray(raw) ? raw.map((x) => asRecord(x) ?? {}) : [];
  }, [current]);
  const summary = asRecord(current?.summary) ?? {};
  const research = asRecord(current?.research_layers) ?? {};
  const changes = Array.isArray(asRecord(changesQ.data)?.items)
    ? (asRecord(changesQ.data)!.items as unknown[])
    : [];
  const traces = Array.isArray(asRecord(tracesQ.data)?.items)
    ? (asRecord(tracesQ.data)!.items as unknown[])
    : [];
  const versions = Array.isArray(asRecord(versionsQ.data)?.items)
    ? (asRecord(versionsQ.data)!.items as unknown[])
    : [];
  const traceDetail = asRecord(asRecord(traceDetailQ.data)?.item);
  const events = Array.isArray(traceDetail?.events)
    ? (traceDetail!.events as unknown[])
    : [];

  const err =
    currentQ.error || changesQ.error || tracesQ.error
      ? toApiError(currentQ.error || changesQ.error || tracesQ.error)
      : null;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="프로세스·버전·Decision Trace (관측 전용)"
        description="REAL entry/exit 정책은 변경하지 않습니다. Research Shadow와 REAL을 구분 표시합니다."
      />
      {err ? (
        <Alert type="error" showIcon title={err.message || "조회 실패"} />
      ) : null}

      <Space wrap>
        <Button
          type={market === "UPBIT" ? "primary" : "default"}
          onClick={() => setMarket("UPBIT")}
        >
          UPBIT
        </Button>
        <Button
          type={market === "KIWOOM" ? "primary" : "default"}
          onClick={() => setMarket("KIWOOM")}
        >
          KIWOOM
        </Button>
        <Switch
          checkedChildren="기술 상세"
          unCheckedChildren="사용자 설명"
          checked={techDetail}
          onChange={setTechDetail}
        />
        <Button
          loading={bootstrapM.isPending}
          onClick={() => bootstrapM.mutate()}
        >
          Bootstrap / Trace 재구성
        </Button>
      </Space>

      <Card size="small">
        <Row gutter={16}>
          <Col xs={24} md={8}>
            <Text type="secondary">자동매매 상태</Text>
            <Title level={4} style={{ margin: 0 }}>
              {String(summary.autotrading_state ?? "—")}
            </Title>
          </Col>
          <Col xs={24} md={8}>
            <Text type="secondary">현재 위치</Text>
            <Title level={4} style={{ margin: 0 }}>
              {String(summary.current_location ?? "—")}
            </Title>
          </Col>
          <Col xs={24} md={8}>
            <Text type="secondary">현재 버전</Text>
            <div>
              <Tag color="blue">{String(pv?.version_code ?? "—")}</Tag>
              {techDetail ? (
                <Text code>{String(pv?.fingerprint ?? "").slice(0, 12)}</Text>
              ) : null}
            </div>
            {techDetail && pv?.git_commit ? (
              <Text type="secondary">git {String(pv.git_commit)}</Text>
            ) : null}
          </Col>
        </Row>
        {current?.first_zero ? (
          <Alert
            style={{ marginTop: 12 }}
            type="warning"
            showIcon
            title={`FIRST_ZERO: ${String(current.first_zero)}`}
          />
        ) : null}
        {market === "KIWOOM" ? (
          <Alert
            style={{ marginTop: 12 }}
            type="error"
            showIcon
            title="KIWOOM_MARKET_DATA_FAILURE_PENDING"
            description="시세/Feed 단계에서 막힘. 이번 화면에서 Feed를 강제 기동하지 않습니다."
          />
        ) : null}
      </Card>

      <Tabs
        items={[
          {
            key: "map",
            label: "현재 프로세스",
            children: (
              <Card size="small" title={`${market} Process Map`}>
                <Space orientation="vertical" style={{ width: "100%" }} size="small">
                  {nodes.map((node, idx) => (
                    <div key={String(node.id ?? idx)}>
                      <Card
                        size="small"
                        hoverable
                        onClick={() => setSelectedNode(node)}
                        styles={{ body: { padding: 12 } }}
                      >
                        <Space wrap>
                          <Tag color={statusColor(String(node.status))}>
                            {statusLabel(String(node.status))}
                          </Tag>
                          <Text strong>{String(node.label ?? node.id)}</Text>
                          {!techDetail ? (
                            <Text type="secondary">{String(node.desc ?? "")}</Text>
                          ) : (
                            <Text code>{String(node.id)}</Text>
                          )}
                        </Space>
                      </Card>
                      {idx < nodes.length - 1 ? (
                        <div style={{ textAlign: "center", opacity: 0.5 }}>↓</div>
                      ) : null}
                    </div>
                  ))}
                </Space>
                <Card size="small" title="Research vs REAL" style={{ marginTop: 16 }}>
                  <Paragraph>
                    REAL Entry: <Tag>{String(research.real_entry ?? "—")}</Tag>
                  </Paragraph>
                  <Paragraph>
                    Entry Shadow: <Tag color="purple">{String(research.entry_shadow ?? "—")}</Tag>
                    {" "}
                    MA Exit Shadow:{" "}
                    <Tag color="purple">{String(research.ma_exit_shadow ?? "—")}</Tag>
                  </Paragraph>
                  <Paragraph>
                    Trading LLM REAL gate:{" "}
                    <Tag>{String(research.trading_llm_real_gate ?? false)}</Tag> (SHADOW)
                  </Paragraph>
                </Card>
              </Card>
            ),
          },
          {
            key: "history",
            label: "버전 이력",
            children: (
              <Card size="small" title="Change Timeline">
                <Timeline
                  items={changes.map((c) => {
                    const row = asRecord(c) ?? {};
                    const diff = asRecord(row.friendly_diff) ?? {};
                    return {
                      color: row.research_only
                        ? "purple"
                        : row.real_policy_changed
                          ? "red"
                          : "blue",
                      content: (
                        <Space orientation="vertical" size={0}>
                          <Space wrap>
                            <Tag>{String(row.change_type)}</Tag>
                            {row.research_only ? <Tag color="purple">RESEARCH</Tag> : null}
                            {row.real_policy_changed ? (
                              <Tag color="red">REAL POLICY</Tag>
                            ) : (
                              <Tag>RELIABILITY/OBS</Tag>
                            )}
                            {row.git_commit ? (
                              <Text code>{String(row.git_commit)}</Text>
                            ) : null}
                          </Space>
                          <Text strong>{String(row.change_summary)}</Text>
                          <Text type="secondary">{String(row.change_reason ?? "")}</Text>
                          <Text>
                            변경 전: {String(diff.before ?? "—")}
                          </Text>
                          <Text>
                            변경 후: {String(diff.after ?? "—")}
                          </Text>
                          {techDetail && Array.isArray(row.evidence_refs) ? (
                            <Text type="secondary">
                              evidence: {(row.evidence_refs as string[]).join(", ")}
                            </Text>
                          ) : null}
                        </Space>
                      ),
                    };
                  })}
                />
                <Table
                  style={{ marginTop: 16 }}
                  size="small"
                  rowKey={(r) => String(asRecord(r)?.process_version_id)}
                  dataSource={versions}
                  pagination={false}
                  columns={[
                    { title: "Code", dataIndex: "version_code" },
                    { title: "Status", dataIndex: "status" },
                    { title: "Git", dataIndex: "git_commit" },
                    { title: "Name", dataIndex: "version_name" },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "traces",
            label: "거래 Trace",
            children: (
              <Card size="small" title="Execution Traces">
                <Table
                  size="small"
                  rowKey={(r) => String(asRecord(r)?.trace_id)}
                  loading={tracesQ.isLoading}
                  dataSource={traces}
                  onRow={(record) => ({
                    onClick: () => {
                      const id = Number(asRecord(record)?.trace_id);
                      if (id > 0) setSelectedTraceId(id);
                    },
                  })}
                  columns={[
                    { title: "ID", dataIndex: "trace_id", width: 70 },
                    { title: "Symbol", dataIndex: "symbol" },
                    { title: "Outcome", dataIndex: "outcome" },
                    { title: "Completeness", dataIndex: "completeness" },
                    {
                      title: "Net",
                      render: (_, r) => {
                        const s = asRecord(asRecord(r)?.summary);
                        return s?.net_est != null ? String(s.net_est) : "—";
                      },
                    },
                    ...(techDetail
                      ? [
                          {
                            title: "Version",
                            dataIndex: "process_version_id",
                          } as const,
                        ]
                      : []),
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "perf",
            label: "버전 성과",
            children: (
              <Card size="small">
                <Alert
                  type="warning"
                  showIcon
                  title="표본이 적어 성능을 단정하기 어렵습니다."
                  description="process_version_id가 연결된 trade만 집계합니다. UNKNOWN version은 제외됩니다."
                />
                <Paragraph style={{ marginTop: 12 }}>
                  현재 버전 성과는 Bootstrap 후 Trace에 연결된 거래 기준입니다.
                  N&lt;30이면 단정 금지.
                </Paragraph>
                {pv?.process_version_id ? (
                  <PerformanceBlock processVersionId={Number(pv.process_version_id)} />
                ) : null}
              </Card>
            ),
          },
        ]}
      />

      <Drawer
        title={String(selectedNode?.label ?? "단계 상세")}
        open={selectedNode != null}
        onClose={() => setSelectedNode(null)}
        size={420}
      >
        {selectedNode ? (
          <Space orientation="vertical">
            <Tag color={statusColor(String(selectedNode.status))}>
              {statusLabel(String(selectedNode.status))}
            </Tag>
            <Paragraph>{String(selectedNode.desc ?? "")}</Paragraph>
            {techDetail ? (
              <>
                <Text code>{String(selectedNode.id)}</Text>
                <pre style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(selectedNode.detail ?? {}, null, 2)}
                </pre>
              </>
            ) : null}
            {selectedNode.id === "ENTRY_SIGNAL" ? (
              <Alert
                type="info"
                title="REAL: PORTFOLIO_BULLISH · Research: E0–E4 Shadow"
              />
            ) : null}
          </Space>
        ) : null}
      </Drawer>

      <Drawer
        title={`Trace #${selectedTraceId ?? ""}`}
        open={selectedTraceId != null}
        onClose={() => setSelectedTraceId(null)}
        size={520}
      >
        {traceDetail ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Space wrap>
              <Tag>{String(traceDetail.symbol)}</Tag>
              <Tag color="blue">{String(traceDetail.outcome)}</Tag>
              <Tag>{String(traceDetail.completeness)}</Tag>
            </Space>
            {techDetail ? (
              <Text type="secondary">
                process_version_id={String(traceDetail.process_version_id)}
              </Text>
            ) : null}
            <Timeline
              items={events.map((e) => {
                const ev = asRecord(e) ?? {};
                return {
                  color:
                    String(ev.status) === "BLOCK" || String(ev.status) === "ERROR"
                      ? "red"
                      : "green",
                  content: (
                    <Space orientation="vertical" size={0}>
                      <Text strong>
                        {String(ev.stage)} · {String(ev.status)}
                      </Text>
                      <Text>{String(ev.summary ?? "")}</Text>
                      {ev.reason_code ? (
                        <Text type="secondary">{String(ev.reason_code)}</Text>
                      ) : null}
                    </Space>
                  ),
                };
              })}
            />
            <pre style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(traceDetail.summary ?? {}, null, 2)}
            </pre>
          </Space>
        ) : (
          <Text type="secondary">로딩…</Text>
        )}
      </Drawer>
    </Space>
  );
}

function PerformanceBlock({ processVersionId }: { processVersionId: number }) {
  const q = useQuery({
    queryKey: queryKeys.admin.autotradingProcessPerformance(processVersionId),
    queryFn: () =>
      adminApi.getAdminAutotradingProcessPerformance(processVersionId),
  });
  const d = asRecord(q.data) ?? {};
  return (
    <Space orientation="vertical">
      <Text>trades={String(d.trades ?? 0)}</Text>
      <Text>win_rate={String(d.win_rate ?? "—")}</Text>
      <Text>net={String(d.net ?? "—")}</Text>
      <Text>pf={String(d.pf ?? "—")}</Text>
      <Text>expectancy={String(d.expectancy ?? "—")}</Text>
      {d.sample_warning ? (
        <Alert
          type="warning"
          showIcon
          title={String(d.sample_warning_message)}
        />
      ) : null}
    </Space>
  );
}
