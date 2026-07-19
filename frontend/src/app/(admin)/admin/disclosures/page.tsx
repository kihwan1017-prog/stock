"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, DatePicker, Form, Input, Space } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminDisclosuresPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [stockCode, setStockCode] = useState("005930");
  const [lastResult, setLastResult] = useState<unknown>(null);

  const listQuery = useQuery({
    queryKey: queryKeys.admin.dartDisclosures({ stock_code: stockCode }),
    queryFn: () =>
      adminApi.listDartDisclosures({
        stock_code: stockCode,
        limit: 50,
      }),
  });

  const syncDisclosures = useMutation({
    mutationFn: (body: {
      stock_code: string;
      start_date: string;
      end_date: string;
    }) => adminApi.syncDartDisclosures(body),
    onSuccess: (data) => {
      message.success("공시 동기화 요청 완료");
      setLastResult(data);
      void qc.invalidateQueries({
        queryKey: queryKeys.admin.dartDisclosures({ stock_code: stockCode }),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const syncCorps = useMutation({
    mutationFn: () => adminApi.syncDartCorps(),
    onSuccess: (data) => {
      message.success("법인코드 동기화 요청 완료");
      setLastResult(data);
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell
      title="공시관리"
      description="DART 공시 조회 · sync"
      extra={
        <Button loading={syncCorps.isPending} onClick={() => syncCorps.mutate()}>
          법인코드 Sync
        </Button>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Form
          layout="inline"
          initialValues={{
            stock_code: stockCode,
            range: [dayjs().subtract(30, "day"), dayjs()],
          }}
          onFinish={(values: {
            stock_code: string;
            range: [dayjs.Dayjs, dayjs.Dayjs];
          }) => {
            const code = values.stock_code.trim().toUpperCase();
            setStockCode(code);
            syncDisclosures.mutate({
              stock_code: code,
              start_date: values.range[0].format("YYYY-MM-DD"),
              end_date: values.range[1].format("YYYY-MM-DD"),
            });
          }}
        >
          <Form.Item name="stock_code" rules={[{ required: true }]}>
            <Input placeholder="stock_code" style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="range" rules={[{ required: true }]}>
            <DatePicker.RangePicker />
          </Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={syncDisclosures.isPending}
          >
            공시 Sync
          </Button>
          <Button
            onClick={() => {
              void listQuery.refetch();
            }}
          >
            조회
          </Button>
        </Form>

        <AdminDataTable
          title={`GET /dart/disclosures?stock_code=${stockCode}`}
          loading={listQuery.isLoading}
          error={listQuery.error ? toApiError(listQuery.error) : null}
          rowKey={(r) => cell(r.disclosure_id ?? r.receipt_no)}
          columns={[
            { title: "일자", dataIndex: "receipt_date", width: 120 },
            { title: "종목", dataIndex: "stock_code", width: 90 },
            { title: "법인", dataIndex: "corp_name", width: 140, ellipsis: true },
            { title: "공시명", dataIndex: "report_name", ellipsis: true },
            { title: "중요도", dataIndex: "importance_score", width: 80 },
            { title: "분류", dataIndex: "category_code", width: 100 },
          ]}
          dataSource={extractRows(listQuery.data)}
        />

        <AdminJsonCard title="최근 sync 응답" data={lastResult} />
      </Space>
    </AdminPageShell>
  );
}
