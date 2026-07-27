"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  TimePicker,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { MarketSessionJobsPanel } from "@/features/admin/market/MarketSessionJobsPanel";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

const STATUS_COLOR: Record<string, string> = {
  VERIFIED: "green",
  UNVERIFIED: "orange",
  STALE: "red",
  MISSING: "red",
  CONFLICT: "magenta",
  DRAFT: "default",
  PENDING_REVIEW: "gold",
  APPROVED: "blue",
  APPLIED: "green",
  APPLIED_WITH_SCHEDULER_ERROR: "volcano",
  REJECTED: "red",
  CANCELLED: "default",
  SUPERSEDED: "default",
};

const SPECIAL_SESSIONS = new Set([
  "DELAYED_OPEN",
  "EARLY_CLOSE",
  "SPECIAL_SESSION",
  "CLOSED",
]);

// STEP 8-5-13 — KRX Session Timeline Phase 한글 라벨/색상
const PHASE_LABEL_KO: Record<string, { label: string; color: string }> = {
  PREOPEN: { label: "장전 준비", color: "blue" },
  OPEN: { label: "정규장 운영 중", color: "green" },
  EXIT_ONLY: { label: "신규 진입 마감", color: "orange" },
  CLOSED: { label: "장 마감", color: "default" },
  POST_CLOSE: { label: "장 마감(정산·복구)", color: "purple" },
  NON_TRADING_DAY: { label: "휴장일", color: "default" },
  CALENDAR_UNAVAILABLE: { label: "Calendar 확인 불가", color: "red" },
};

const DEFAULT_REGULAR_OPEN_HM = "09:00";
const DEFAULT_REGULAR_CLOSE_HM = "15:30";

/** ISO datetime → "HH:mm" (표시용). 값이 없으면 "-" */
function hm(iso: string | null | undefined): string {
  if (!iso) return "-";
  const parsed = dayjs(iso);
  return parsed.isValid() ? parsed.format("HH:mm") : "-";
}

/** 09:00/15:30 정규 기본값과 다르면 지연개장/조기종료 등 특이일로 강조 표시 */
function TimelineTimeField({
  iso,
  defaultHm,
}: {
  iso: string | null | undefined;
  defaultHm?: string;
}) {
  const display = hm(iso);
  const differs = Boolean(defaultHm) && display !== "-" && display !== defaultHm;
  return (
    <Typography.Text strong={differs} type={differs ? "warning" : undefined}>
      {display}
      {differs ? " (기본값과 다름)" : ""}
    </Typography.Text>
  );
}

/** STEP 8-5-11 — Admin KRX Calendar + Change Request */
export function MarketCalendarPanel() {
  const qc = useQueryClient();
  const [range, setRange] = useState(() => [
    dayjs().startOf("month"),
    dayjs().endOf("month"),
  ]);
  const [editOpen, setEditOpen] = useState(false);
  const [editDate, setEditDate] = useState<string | null>(null);
  const [editRevision, setEditRevision] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [timelineDate, setTimelineDate] = useState(() => dayjs());
  const [form] = Form.useForm();

  const start = range[0]?.format("YYYY-MM-DD") ?? "";
  const end = range[1]?.format("YYYY-MM-DD") ?? "";
  const timelineDateStr = timelineDate.format("YYYY-MM-DD");

  const listQuery = useQuery({
    queryKey: ["admin", "market-calendar", start, end],
    queryFn: () =>
      adminApi.listAdminMarketCalendar({
        exchange_code: "KRX",
        start_date: start,
        end_date: end,
      }),
    enabled: Boolean(start && end),
  });

  const coverageQuery = useQuery({
    queryKey: ["admin", "market-calendar-coverage"],
    queryFn: () => adminApi.getAdminMarketCalendarCoverage(),
  });

  const changeHealthQuery = useQuery({
    queryKey: ["admin", "market-calendar-change-health"],
    queryFn: () => adminApi.getAdminMarketCalendarChangeHealth(),
  });

  const requestsQuery = useQuery({
    queryKey: ["admin", "market-calendar-change-requests"],
    queryFn: () =>
      adminApi.listAdminCalendarChangeRequests({ exchange_code: "KRX" }),
  });

  // STEP 8-5-13 — 선택 일자 Session Timeline / 동적 Job
  const timelineQuery = useQuery({
    queryKey: ["admin", "market-calendar-timeline", timelineDateStr],
    queryFn: () =>
      adminApi.getAdminMarketCalendarTimeline("KRX", timelineDateStr),
    enabled: Boolean(timelineDateStr),
  });

  const jobsQuery = useQuery({
    queryKey: ["admin", "market-calendar-jobs", timelineDateStr],
    queryFn: () => adminApi.getAdminMarketCalendarJobs("KRX", timelineDateStr),
    enabled: Boolean(timelineDateStr),
  });

  const recomputeJobsMut = useMutation({
    mutationFn: () =>
      adminApi.recomputeAdminMarketCalendarJobs("KRX", timelineDateStr),
    onSuccess: async () => {
      await qc.invalidateQueries({
        queryKey: ["admin", "market-calendar-jobs", timelineDateStr],
      });
      await qc.invalidateQueries({
        queryKey: ["admin", "market-calendar-timeline", timelineDateStr],
      });
    },
  });

  const syncMut = useMutation({
    mutationFn: () =>
      adminApi.syncAdminMarketCalendar({ mark_verified: true, past_years: 1 }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["admin", "market-calendar"] });
      await qc.invalidateQueries({
        queryKey: ["admin", "market-calendar-coverage"],
      });
    },
  });

  const verifyMut = useMutation({
    mutationFn: (calendarDate: string) =>
      adminApi.verifyAdminMarketCalendarDay("KRX", calendarDate),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["admin", "market-calendar"] });
      await qc.invalidateQueries({
        queryKey: ["admin", "market-calendar-change-requests"],
      });
    },
  });

  const updateMut = useMutation({
    mutationFn: (values: {
      is_trading_day: boolean;
      session_type: string;
      holiday_name?: string;
      reason: string;
      emergency?: boolean;
      source_reference?: string;
      regular_open_at?: dayjs.Dayjs | null;
      regular_close_at?: dayjs.Dayjs | null;
    }) =>
      adminApi.updateAdminMarketCalendarDay("KRX", editDate!, {
        is_trading_day: values.is_trading_day,
        session_type: values.session_type,
        holiday_name: values.holiday_name ?? null,
        reason: values.reason,
        emergency: Boolean(values.emergency),
        apply_now: !values.emergency,
        source_reference: values.source_reference ?? null,
        expected_revision: editRevision,
        regular_open_at: values.regular_open_at
          ? values.regular_open_at.format("HH:mm:ss")
          : null,
        regular_close_at: values.regular_close_at
          ? values.regular_close_at.format("HH:mm:ss")
          : null,
      }),
    onSuccess: async () => {
      setEditOpen(false);
      await qc.invalidateQueries({ queryKey: ["admin", "market-calendar"] });
      await qc.invalidateQueries({
        queryKey: ["admin", "market-calendar-change-requests"],
      });
      await qc.invalidateQueries({
        queryKey: ["admin", "market-calendar-change-health"],
      });
    },
  });

  const actionMut = useMutation({
    mutationFn: async (payload: {
      id: number;
      action: "submit" | "approve" | "reject" | "apply" | "cancel";
    }) => {
      if (payload.action === "submit") {
        return adminApi.submitAdminCalendarChangeRequest(payload.id);
      }
      if (payload.action === "approve") {
        return adminApi.approveAdminCalendarChangeRequest(payload.id);
      }
      if (payload.action === "reject") {
        return adminApi.rejectAdminCalendarChangeRequest(
          payload.id,
          "rejected from admin UI",
        );
      }
      if (payload.action === "apply") {
        return adminApi.applyAdminCalendarChangeRequest(payload.id);
      }
      return adminApi.cancelAdminCalendarChangeRequest(payload.id);
    },
    onSuccess: async () => {
      await qc.invalidateQueries({
        queryKey: ["admin", "market-calendar-change-requests"],
      });
      await qc.invalidateQueries({ queryKey: ["admin", "market-calendar"] });
      await qc.invalidateQueries({
        queryKey: ["admin", "market-calendar-change-health"],
      });
    },
  });

  const rows = extractRows(listQuery.data);
  const requestRows = extractRows(requestsQuery.data);
  const coverage = asRecord(asRecord(coverageQuery.data)?.coverage);
  const changeHealth = asRecord(changeHealthQuery.data);
  const busy =
    syncMut.isPending ||
    updateMut.isPending ||
    verifyMut.isPending ||
    actionMut.isPending;

  const coverageTag = useMemo(() => {
    const ok = Boolean(coverage?.live_trading_allowed);
    return (
      <Tag color={ok ? "green" : "red"}>
        {ok ? "LIVE 가능" : "Coverage 부족 / LIVE 차단"}
      </Tag>
    );
  }, [coverage]);

  const detailRow = useMemo(() => {
    if (detailId == null) return null;
    return (
      requestRows.find(
        (r) => Number(asRecord(r)?.change_request_id) === detailId,
      ) ?? null
    );
  }, [detailId, requestRows]);

  const timeline = asRecord(timelineQuery.data);
  const jobRows = extractRows(jobsQuery.data);
  const currentPhase = String(timeline?.current_phase ?? "");
  const phaseMeta = PHASE_LABEL_KO[currentPhase];

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size="middle">
      <Card
        size="small"
        title="Session Timeline (STEP 8-5-13)"
        extra={
          <Space>
            <DatePicker
              value={timelineDate}
              onChange={(v) => {
                if (v) setTimelineDate(v);
              }}
              allowClear={false}
            />
            <Button
              loading={timelineQuery.isFetching || jobsQuery.isFetching}
              onClick={() => {
                void timelineQuery.refetch();
                void jobsQuery.refetch();
              }}
            >
              새로고침
            </Button>
            <Button
              type="primary"
              loading={recomputeJobsMut.isPending}
              onClick={() => recomputeJobsMut.mutate()}
            >
              Job 재계산
            </Button>
            <Button
              size="small"
              type="link"
              href="#calendar-change-requests"
            >
              변경 요청 이력 →
            </Button>
          </Space>
        }
      >
        {timelineQuery.isError ? (
          <Alert
            type="error"
            showIcon
            title="Timeline 조회 실패"
            description={toApiError(timelineQuery.error).message}
            style={{ marginBottom: 12 }}
          />
        ) : null}
        {recomputeJobsMut.isError ? (
          <Alert
            type="error"
            showIcon
            title="Job 재계산 실패"
            description={toApiError(recomputeJobsMut.error).message}
            style={{ marginBottom: 12 }}
          />
        ) : null}
        {recomputeJobsMut.isSuccess ? (
          <Alert
            type="success"
            showIcon
            title={`Job 재계산 완료 — registered=${cell(
              asRecord(recomputeJobsMut.data)?.registered,
            )} / removed=${cell(asRecord(recomputeJobsMut.data)?.removed)}`}
            style={{ marginBottom: 12 }}
            closable
          />
        ) : null}

        <Descriptions size="small" bordered column={2}>
          <Descriptions.Item label="Current Phase">
            <Tag color={phaseMeta?.color ?? "default"}>
              {phaseMeta?.label ?? cell(currentPhase || "-")}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Calendar Revision">
            {cell(timeline?.revision)}
          </Descriptions.Item>
          <Descriptions.Item label="Session Type">
            {cell(timeline?.session_type)}
          </Descriptions.Item>
          <Descriptions.Item label="Reason Code">
            {cell(timeline?.reason_code)}
          </Descriptions.Item>
          <Descriptions.Item label="Pre-open Recovery">
            <TimelineTimeField iso={timeline?.recovery_preopen_at as string} />
          </Descriptions.Item>
          <Descriptions.Item label="Regular Open">
            <TimelineTimeField
              iso={timeline?.regular_open_at as string}
              defaultHm={DEFAULT_REGULAR_OPEN_HM}
            />
          </Descriptions.Item>
          <Descriptions.Item label="New Entry Cutoff">
            <TimelineTimeField iso={timeline?.new_entry_cutoff_at as string} />
          </Descriptions.Item>
          <Descriptions.Item label="Regular Close">
            <TimelineTimeField
              iso={timeline?.regular_close_at as string}
              defaultHm={DEFAULT_REGULAR_CLOSE_HM}
            />
          </Descriptions.Item>
          <Descriptions.Item label="Post-close Recovery">
            <TimelineTimeField iso={timeline?.recovery_postclose_at as string} />
          </Descriptions.Item>
          <Descriptions.Item label="Snapshot">
            <TimelineTimeField iso={timeline?.snapshot_at as string} />
          </Descriptions.Item>
          <Descriptions.Item label="AI Analysis">
            <TimelineTimeField iso={timeline?.analysis_at as string} />
          </Descriptions.Item>
          <Descriptions.Item label="다음 전환">
            {timeline?.next_transition_phase
              ? `${cell(timeline.next_transition_phase)} @ ${hm(
                  timeline.next_transition_at as string,
                )}`
              : "-"}
          </Descriptions.Item>
        </Descriptions>

        <Typography.Title level={5} style={{ marginTop: 16 }}>
          동적 Job (calendar_scheduler_recompute)
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          위 시각 기준으로 등록된 1회성 Job이 Primary이며, 15:40/16:30 고정
          Cron은 이 Job이 없거나 실패했을 때만 Fallback으로 동작합니다(현재
          고정 Cron 스킵 사유는 서버 로그에서만 확인 가능 — Job History API
          미연동).
        </Typography.Paragraph>
        <Table
          size="small"
          rowKey={(r) => String(asRecord(r)?.job_id ?? Math.random())}
          loading={jobsQuery.isLoading}
          dataSource={jobRows}
          pagination={false}
          locale={{ emptyText: "등록된 동적 Job 없음" }}
          columns={[
            { title: "Job Type", dataIndex: "job_type", render: cell },
            {
              title: "상태",
              dataIndex: "status",
              render: (v) => (
                <Tag color={STATUS_COLOR[String(v)] ?? "blue"}>{cell(v)}</Tag>
              ),
            },
            {
              title: "실행 예정",
              dataIndex: "run_at",
              render: (v) => cell(v),
            },
            { title: "Rev", dataIndex: "revision", width: 60, render: cell },
          ]}
        />
      </Card>

      <MarketSessionJobsPanel />

      <Card
        size="small"
        title="KRX 거래일 캘린더"
        extra={
          <Space>
            <DatePicker.RangePicker
              value={range as [dayjs.Dayjs, dayjs.Dayjs]}
              onChange={(v) => {
                if (v?.[0] && v?.[1]) setRange([v[0], v[1]]);
              }}
            />
            <Button
              loading={listQuery.isFetching}
              onClick={() => void listQuery.refetch()}
            >
              새로고침
            </Button>
            <Button
              type="primary"
              loading={syncMut.isPending}
              disabled={busy}
              onClick={() => syncMut.mutate()}
            >
              Calendar Sync
            </Button>
          </Space>
        }
      >
        <Space style={{ marginBottom: 12 }} wrap>
          {coverageTag}
          <Typography.Text type="secondary">
            pending={cell(changeHealth?.pending_change_requests)} / conflict=
            {cell(changeHealth?.conflict_change_requests)} / today_session=
            {cell(changeHealth?.today_session_type)} / rev=
            {cell(changeHealth?.today_revision)}
          </Typography.Text>
        </Space>
        {syncMut.isError ? (
          <Typography.Text type="danger">
            {toApiError(syncMut.error).message}
          </Typography.Text>
        ) : null}
        <Table
          size="small"
          rowKey={(r) => String(asRecord(r)?.calendar_date ?? Math.random())}
          loading={listQuery.isLoading}
          dataSource={rows}
          pagination={{ pageSize: 15 }}
          columns={[
            {
              title: "날짜",
              dataIndex: "calendar_date",
              width: 110,
              render: (v) => cell(v),
            },
            {
              title: "거래일",
              dataIndex: "is_trading_day",
              width: 80,
              render: (v) => (v ? "Y" : "N"),
            },
            {
              title: "Session",
              dataIndex: "session_type",
              width: 120,
              render: (v) => (
                <Space>
                  {cell(v)}
                  {SPECIAL_SESSIONS.has(String(v)) ? (
                    <Tag color="purple">특별</Tag>
                  ) : null}
                </Space>
              ),
            },
            {
              title: "개장",
              dataIndex: "regular_open_at",
              render: (v) => cell(v),
            },
            {
              title: "종료",
              dataIndex: "regular_close_at",
              render: (v) => cell(v),
            },
            {
              title: "Rev",
              dataIndex: "revision",
              width: 60,
              render: (v) => cell(v),
            },
            {
              title: "휴장/사유",
              key: "holiday",
              render: (_, row) => {
                const r = asRecord(row);
                return cell(r?.holiday_name ?? r?.closure_reason);
              },
            },
            {
              title: "Source",
              dataIndex: "source_type",
              render: (v) => cell(v),
            },
            {
              title: "검증",
              dataIndex: "verified_status",
              render: (v) => (
                <Tag color={STATUS_COLOR[String(v)] ?? "default"}>
                  {cell(v)}
                </Tag>
              ),
            },
            {
              title: "작업",
              key: "actions",
              render: (_, row) => {
                const r = asRecord(row);
                const d = String(r?.calendar_date ?? "");
                return (
                  <Space>
                    <Button
                      size="small"
                      disabled={busy}
                      onClick={() => {
                        // destroyOnHidden 시 Form 연결 전 setFieldsValue 금지
                        setEditDate(d);
                        setEditRevision(
                          r?.revision != null ? Number(r.revision) : null,
                        );
                        setEditOpen(true);
                      }}
                    >
                      변경 요청
                    </Button>
                    <Button
                      size="small"
                      disabled={busy}
                      loading={verifyMut.isPending}
                      onClick={() => {
                        Modal.confirm({
                          title: "검증 적용",
                          content: `${d} 를 VERIFIED 변경 요청으로 적용합니다.`,
                          onOk: () => verifyMut.mutateAsync(d),
                        });
                      }}
                    >
                      검증
                    </Button>
                  </Space>
                );
              },
            },
          ]}
        />

        <Modal
          title={`캘린더 변경 요청 ${editDate ?? ""}`}
          open={editOpen}
          onCancel={() => setEditOpen(false)}
          confirmLoading={updateMut.isPending}
          onOk={() => form.submit()}
          okText="요청 생성·적용"
          destroyOnHidden
          afterOpenChange={(open) => {
            if (!open || !editDate) return;
            const r = asRecord(
              rows.find(
                (row) => String(asRecord(row)?.calendar_date ?? "") === editDate,
              ),
            );
            if (!r) return;
            form.setFieldsValue({
              is_trading_day: Boolean(r.is_trading_day),
              session_type: r.session_type ?? "REGULAR",
              holiday_name: r.holiday_name,
              reason: "",
              emergency: false,
              source_reference: "",
              regular_open_at: r.regular_open_at
                ? dayjs(String(r.regular_open_at), "HH:mm:ss")
                : null,
              regular_close_at: r.regular_close_at
                ? dayjs(String(r.regular_close_at), "HH:mm:ss")
                : null,
            });
          }}
        >
          <Form
            form={form}
            layout="vertical"
            onFinish={(values) => {
              const run = () => updateMut.mutate(values);
              if (values.emergency) {
                Modal.confirm({
                  title: "긴급 적용 확인",
                  content:
                    "긴급 변경은 즉시 적용되며 강한 Audit이 남습니다. 계속할까요?",
                  okType: "danger",
                  onOk: run,
                });
                return;
              }
              run();
            }}
          >
            <Form.Item
              name="is_trading_day"
              label="거래일"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item
              name="session_type"
              label="Session"
              rules={[{ required: true }]}
            >
              <Select
                options={[
                  "CLOSED",
                  "REGULAR",
                  "DELAYED_OPEN",
                  "EARLY_CLOSE",
                  "SPECIAL_SESSION",
                ].map((v) => ({ value: v, label: v }))}
              />
            </Form.Item>
            <Form.Item name="regular_open_at" label="개장">
              <TimePicker format="HH:mm" style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="regular_close_at" label="종료">
              <TimePicker format="HH:mm" style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="holiday_name" label="휴장명">
              <Input />
            </Form.Item>
            <Form.Item name="emergency" label="긴급" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="source_reference" label="Source Reference">
              <Input placeholder="공지번호/URL 등" />
            </Form.Item>
            <Form.Item
              name="reason"
              label="변경 사유"
              rules={[{ required: true, min: 3 }]}
            >
              <Input.TextArea rows={2} />
            </Form.Item>
            {updateMut.isError ? (
              <Typography.Text type="danger">
                {toApiError(updateMut.error).message}
              </Typography.Text>
            ) : null}
          </Form>
        </Modal>
      </Card>

      <Card size="small" title="Calendar 변경 요청" id="calendar-change-requests">
        <Table
          size="small"
          rowKey={(r) =>
            String(asRecord(r)?.change_request_id ?? Math.random())
          }
          loading={requestsQuery.isLoading}
          dataSource={requestRows}
          pagination={{ pageSize: 10 }}
          columns={[
            {
              title: "ID",
              dataIndex: "change_request_id",
              width: 70,
              render: (v) => cell(v),
            },
            {
              title: "날짜",
              dataIndex: "market_date",
              width: 110,
              render: (v) => cell(v),
            },
            {
              title: "유형",
              dataIndex: "change_type",
              render: (v) => cell(v),
            },
            {
              title: "상태",
              dataIndex: "status",
              render: (v) => (
                <Tag color={STATUS_COLOR[String(v)] ?? "default"}>
                  {cell(v)}
                </Tag>
              ),
            },
            {
              title: "긴급",
              dataIndex: "emergency",
              width: 60,
              render: (v) => (v ? "Y" : "N"),
            },
            {
              title: "요청자",
              dataIndex: "requested_by",
              render: (v) => cell(v),
            },
            {
              title: "Scheduler",
              dataIndex: "scheduler_recompute_status",
              render: (v) => cell(v),
            },
            {
              title: "작업",
              key: "actions",
              render: (_, row) => {
                const r = asRecord(row);
                const id = Number(r?.change_request_id);
                const st = String(r?.status ?? "");
                return (
                  <Space wrap>
                    <Button size="small" onClick={() => setDetailId(id)}>
                      상세
                    </Button>
                    {st === "DRAFT" || st === "CONFLICT" ? (
                      <Button
                        size="small"
                        disabled={busy}
                        onClick={() =>
                          actionMut.mutate({ id, action: "submit" })
                        }
                      >
                        Submit
                      </Button>
                    ) : null}
                    {st === "PENDING_REVIEW" ? (
                      <>
                        <Button
                          size="small"
                          disabled={busy}
                          onClick={() =>
                            Modal.confirm({
                              title: "승인 확인",
                              onOk: () =>
                                actionMut.mutateAsync({
                                  id,
                                  action: "approve",
                                }),
                            })
                          }
                        >
                          Approve
                        </Button>
                        <Button
                          size="small"
                          danger
                          disabled={busy}
                          onClick={() =>
                            Modal.confirm({
                              title: "거절 확인",
                              onOk: () =>
                                actionMut.mutateAsync({
                                  id,
                                  action: "reject",
                                }),
                            })
                          }
                        >
                          Reject
                        </Button>
                      </>
                    ) : null}
                    {st === "APPROVED" ? (
                      <Button
                        size="small"
                        type="primary"
                        disabled={busy}
                        onClick={() =>
                          Modal.confirm({
                            title: "적용 확인",
                            content: "Calendar Revision이 증가합니다.",
                            onOk: () =>
                              actionMut.mutateAsync({ id, action: "apply" }),
                          })
                        }
                      >
                        Apply
                      </Button>
                    ) : null}
                    {["DRAFT", "PENDING_REVIEW", "APPROVED", "CONFLICT"].includes(
                      st,
                    ) ? (
                      <Button
                        size="small"
                        disabled={busy}
                        onClick={() =>
                          actionMut.mutate({ id, action: "cancel" })
                        }
                      >
                        Cancel
                      </Button>
                    ) : null}
                  </Space>
                );
              },
            },
          ]}
        />
        {actionMut.isError ? (
          <Typography.Text type="danger">
            {toApiError(actionMut.error).message}
          </Typography.Text>
        ) : null}
      </Card>

      <Modal
        title={`변경 요청 #${detailId ?? ""}`}
        open={detailId != null}
        onCancel={() => setDetailId(null)}
        footer={null}
        width={720}
      >
        {detailRow ? (
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
            {JSON.stringify(asRecord(detailRow), null, 2)}
          </pre>
        ) : (
          <Typography.Text type="secondary">요청 없음</Typography.Text>
        )}
      </Modal>
    </Space>
  );
}
