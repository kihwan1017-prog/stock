"use client";

/**
 * STEP 9-7 — Runtime Pre-flight Check 패널.
 * LIVE ON 전 운영 조건 점검 · 상태 변경 없음.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import type { RuntimePreflightCheck } from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function statusColor(status: string): string {
  const s = status.toUpperCase();
  if (s === "PASS") return "success";
  if (s === "WARN" || s === "WARNING") return "warning";
  if (s === "FAIL" || s === "BLOCKED" || s === "STALE") return "error";
  if (s === "NOT_APPLICABLE" || s === "FRESH") return "default";
  return "default";
}

function downloadJson(filename: string, payload: unknown) {
  const safe = adminApi.sanitizePreflightExport(payload);
  const blob = new Blob([JSON.stringify(safe, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function savePdfViaPrint(
  title: string,
  checks: RuntimePreflightCheck[],
  overall: string,
  estimatedReady: string,
  freshness: string,
) {
  // PDF 경로/서버 FS 미노출 — 브라우저 print/Blob 만 사용
  const safeChecks = adminApi.sanitizePreflightExport(checks) as RuntimePreflightCheck[];
  const rows = safeChecks
    .map(
      (c) =>
        `<tr><td>${escapeHtml(String(c.code ?? ""))}</td>` +
        `<td>${escapeHtml(String(c.name ?? ""))}</td>` +
        `<td>${escapeHtml(String(c.status ?? ""))}</td>` +
        `<td>${escapeHtml(String(c.blocking ? "Y" : "N"))}</td>` +
        `<td>${escapeHtml(String(c.message ?? ""))}</td>` +
        `<td>${escapeHtml(String(c.remediation ?? ""))}</td></tr>`,
    )
    .join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"/><title>${escapeHtml(title)}</title>
  <style>
    body{font-family:Segoe UI,Arial,sans-serif;padding:24px;color:#111}
    h1{font-size:20px;margin:0 0 8px}
    .meta{color:#555;margin-bottom:16px}
    table{border-collapse:collapse;width:100%}
    th,td{border:1px solid #ccc;padding:8px;text-align:left;font-size:12px}
    th{background:#f5f5f5}
  </style></head><body>
  <h1>${escapeHtml(title)}</h1>
  <div class="meta">Overall: <strong>${escapeHtml(overall)}</strong>
   · estimated_ready: ${escapeHtml(estimatedReady)}
   · freshness: ${escapeHtml(freshness)}</div>
  <table><thead><tr>
    <th>Code</th><th>Check</th><th>Status</th><th>Blocking</th><th>Message</th><th>Remediation</th>
  </tr></thead>
  <tbody>${rows}</tbody></table>
  <script>window.onload=()=>{window.print();}</script>
  </body></html>`;
  const win = window.open("", "_blank", "noopener,noreferrer,width=900,height=700");
  if (!win) return;
  win.document.open();
  win.document.write(html);
  win.document.close();
}

export function RuntimePreflightPanel() {
  const [nowMs, setNowMs] = useState(() => Date.now());

  const query = useQuery({
    queryKey: queryKeys.admin.runtimePreflight(),
    queryFn: () => adminApi.getRuntimePreflight({ mode: "LIVE_ON" }),
    refetchInterval: 30_000,
  });

  // TTL 만료 시 UI 를 STALE 로 갱신
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 5_000);
    return () => window.clearInterval(id);
  }, []);

  const data = query.data;
  const overall = String(data?.overall_status ?? "-");
  const freshness = adminApi.evaluatePreflightFreshness(
    data?.checked_at ?? data?.freshness?.checked_at,
    Number(data?.freshness?.ttl_seconds) || adminApi.PREFLIGHT_TTL_SECONDS,
    nowMs,
  );
  const liveOnAllowed = adminApi.isPreflightLiveOnAllowed(data, nowMs);
  const estimatedReady =
    data?.estimated_ready == null ? "null" : String(data.estimated_ready);
  const checks = data?.checks ?? [];

  const columns = useMemo(
    () => [
      {
        title: "코드",
        dataIndex: "code",
        width: 130,
      },
      {
        title: "검사 항목",
        dataIndex: "name",
        width: 140,
      },
      {
        title: "상태",
        dataIndex: "status",
        width: 110,
        render: (value: string) => (
          <Tag color={statusColor(value)}>{value}</Tag>
        ),
      },
      {
        title: "Blocking",
        dataIndex: "blocking",
        width: 90,
        render: (value: boolean | undefined) =>
          value ? <Tag color="error">Y</Tag> : <Tag>N</Tag>,
      },
      {
        title: "메시지",
        dataIndex: "message",
      },
      {
        title: "조치",
        dataIndex: "remediation",
        width: 220,
        render: (value: string | null | undefined) => value || "-",
      },
    ],
    [],
  );

  return (
    <AdminPageShell
      title="Pre-flight Check"
      description="LIVE ON 전 운영 조건을 자동 점검합니다. 상태 변경·실주문은 수행하지 않습니다."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {query.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(query.error).message}
          />
        ) : null}

        <Card size="small">
          <Space wrap>
            <Button
              type="primary"
              loading={query.isFetching}
              onClick={() => void query.refetch()}
            >
              검사 / 새로고침
            </Button>
            <Button
              disabled={!data}
              onClick={() =>
                savePdfViaPrint(
                  "Runtime Pre-flight Check",
                  checks,
                  overall,
                  estimatedReady,
                  freshness.status,
                )
              }
            >
              PDF 저장
            </Button>
            <Button
              disabled={!data}
              onClick={() =>
                downloadJson(
                  `runtime-preflight-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`,
                  data,
                )
              }
            >
              JSON 다운로드
            </Button>
          </Space>
        </Card>

        <Alert
          type={liveOnAllowed ? "success" : "error"}
          showIcon
          title={`Overall: ${overall} · Freshness: ${freshness.status}`}
          description={
            <Space orientation="vertical" size={4}>
              <Typography.Text>
                {liveOnAllowed
                  ? "READY_FOR_LIVE + FRESH — LIVE ON UI 활성 (서버에서 Pre-flight 재검증)"
                  : freshness.status === "STALE"
                    ? "STALE — 60초 초과. 재검사 후 LIVE ON 가능"
                    : "BLOCKED — LIVE ON 버튼 비활성"}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                PASS {data?.summary?.pass ?? "-"} · WARN{" "}
                {data?.summary?.warn ?? "-"} · FAIL {data?.summary?.fail ?? "-"}{" "}
                · N/A {data?.summary?.not_applicable ?? "-"} · estimated_ready{" "}
                {estimatedReady} · TTL {adminApi.PREFLIGHT_TTL_SECONDS}s ·
                checked_at {data?.checked_at ?? "-"}
              </Typography.Text>
              {!liveOnAllowed && (data?.blockers?.length ?? 0) > 0 ? (
                <Typography.Text type="danger">
                  blockers:{" "}
                  {(data?.blockers ?? [])
                    .map((b) => `${b.code}: ${b.message}`)
                    .join(" · ")}
                </Typography.Text>
              ) : null}
            </Space>
          }
        />

        <Card title="Checks" size="small" loading={query.isLoading}>
          <Table<RuntimePreflightCheck>
            size="small"
            rowKey={(row) => row.code}
            pagination={false}
            dataSource={checks}
            columns={columns}
          />
        </Card>

        <Card size="small" title="LIVE ON">
          <Button type="primary" danger disabled={!liveOnAllowed}>
            LIVE ON
          </Button>
          <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
            Pre-flight 가 READY_FOR_LIVE 이고 최신(FRESH, 60초)일 때만 활성화됩니다.
            실제 LIVE ON 은 이 화면에서 실행하지 않으며, 전체계좌 Runtime 제어에서
            별도 승인 후 진행합니다. 서버 API 는 Pre-flight 를 재계산합니다.
          </Typography.Paragraph>
        </Card>
      </Space>
    </AdminPageShell>
  );
}
