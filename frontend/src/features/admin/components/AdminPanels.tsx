"use client";

import { Alert, Button, Card, Empty, Space, Table, Typography } from "antd";
import type { ColumnsType, TablePaginationConfig, TableProps } from "antd/es/table";
import type { ReactNode } from "react";

interface UnimplementedApiPanelProps {
  feature: string;
  reason: string;
  expectedApis?: string[];
  relatedApis?: string[];
  /** 운영형 껍데기 — 비활성 CRUD 버튼 */
  showShell?: boolean;
}

/**
 * Backend API가 없을 때 표시.
 * Placeholder가 아니라 운영 화면 형태로, 액션은 비활성.
 */
export function UnimplementedApiPanel({
  feature,
  reason,
  expectedApis = [],
  relatedApis = [],
  showShell = true,
}: UnimplementedApiPanelProps) {
  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="warning"
        showIcon
        title={`${feature} — 미구현 API`}
        description={
          <div>
            <Typography.Paragraph style={{ marginBottom: 8 }}>
              {reason}
            </Typography.Paragraph>
            {expectedApis.length > 0 ? (
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                필요한 API: {expectedApis.join(", ")}
              </Typography.Paragraph>
            ) : null}
            {relatedApis.length > 0 ? (
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                관련·참고 API: {relatedApis.join(", ")}
              </Typography.Paragraph>
            ) : null}
          </div>
        }
      />
      {showShell ? (
        <Card
          title={`${feature} 목록`}
          extra={
            <Space>
              <Button disabled>등록</Button>
              <Button disabled>수정</Button>
              <Button danger disabled>
                삭제
              </Button>
            </Space>
          }
          size="small"
        >
          <Space style={{ marginBottom: 12 }} wrap>
            <Typography.Text type="secondary">검색·필터·정렬·페이징 UI 준비됨</Typography.Text>
            <Button disabled>검색</Button>
            <Button disabled>필터</Button>
          </Space>
          <Table
            size="small"
            rowKey="id"
            columns={[
              { title: "ID", dataIndex: "id" },
              { title: "이름", dataIndex: "name" },
              { title: "상태", dataIndex: "status" },
              { title: "수정일", dataIndex: "updated_at" },
            ]}
            dataSource={[]}
            pagination={{ pageSize: 10, showSizeChanger: true }}
            locale={{ emptyText: <Empty description="Backend API 연결 대기" /> }}
          />
        </Card>
      ) : null}
    </Space>
  );
}

interface AdminDataTableProps<T extends object> {
  title?: string;
  loading?: boolean;
  error?: Error | null;
  columns: ColumnsType<T>;
  dataSource: T[];
  rowKey?: string | ((record: T) => string);
  pagination?: TablePaginationConfig | false;
  extra?: ReactNode;
  toolbar?: ReactNode;
  onChange?: TableProps<T>["onChange"];
}

export function AdminDataTable<T extends object>({
  title,
  loading,
  error,
  columns,
  dataSource,
  rowKey = "id",
  pagination = { pageSize: 20, showSizeChanger: true },
  extra,
  toolbar,
  onChange,
}: AdminDataTableProps<T>) {
  return (
    <Card title={title} extra={extra} size="small">
      {toolbar ? <div style={{ marginBottom: 12 }}>{toolbar}</div> : null}
      {error ? (
        <Alert
          type="error"
          showIcon
          title="API 오류"
          description={error.message}
          style={{ marginBottom: 12 }}
        />
      ) : null}
      <Table<T>
        size="small"
        loading={loading}
        columns={columns}
        dataSource={dataSource}
        rowKey={rowKey}
        pagination={pagination}
        scroll={{ x: true }}
        onChange={onChange}
      />
    </Card>
  );
}

interface AdminJsonCardProps {
  title: string;
  loading?: boolean;
  error?: Error | null;
  data?: unknown;
  extra?: ReactNode;
}

export function AdminJsonCard({
  title,
  loading,
  error,
  data,
  extra,
}: AdminJsonCardProps) {
  let text = "";
  try {
    text = JSON.stringify(data, null, 2);
  } catch {
    text = String(data);
  }

  return (
    <Card title={title} extra={extra} size="small">
      {error ? (
        <Alert type="error" showIcon title="API 오류" description={error.message} />
      ) : null}
      {!error && (data === undefined || data === null) && !loading ? (
        <Empty description="데이터 없음" />
      ) : null}
      {!error && data !== undefined && data !== null ? (
        <pre
          style={{
            margin: 0,
            maxHeight: 420,
            overflow: "auto",
            fontSize: 12,
            padding: 12,
            borderRadius: 8,
            background: "var(--app-bg, #fafafa)",
          }}
        >
          {loading ? "불러오는 중..." : text}
        </pre>
      ) : null}
      {loading && (data === undefined || data === null) ? (
        <Typography.Text type="secondary">불러오는 중...</Typography.Text>
      ) : null}
    </Card>
  );
}
