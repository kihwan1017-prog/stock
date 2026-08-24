"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Drawer,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import type { MemberCleanupCandidate } from "@/features/admin/api/adminApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const CONFIRM_PHRASE = "DELETE_TEST_ACCOUNTS";

export function MemberCleanupPreviewPanel() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [mode, setMode] = useState<"deactivate" | "soft_delete">("deactivate");
  const [confirmPhrase, setConfirmPhrase] = useState("");
  const [backupConfirmed, setBackupConfirmed] = useState(false);
  const [previewData, setPreviewData] = useState<Record<string, unknown> | null>(
    null,
  );

  const candidatesQuery = useQuery({
    queryKey: queryKeys.admin.memberCleanupCandidates({ includeDeleted }),
    queryFn: () =>
      adminApi.listMemberCleanupCandidates({ include_deleted: includeDeleted }),
    enabled: drawerOpen && loaded,
  });

  const previewMut = useMutation({
    mutationFn: adminApi.previewMemberCleanup,
    onSuccess: (data) => {
      setPreviewData(
        data && typeof data === "object"
          ? (data as Record<string, unknown>)
          : null,
      );
      message.info("Preview 완료 — DB 변경 없음");
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const executeMut = useMutation({
    mutationFn: adminApi.executeMemberCleanup,
    onSuccess: (data) => {
      message.success("테스트 계정 정리가 실행되었습니다.");
      setPreviewData(null);
      setSelectedUserIds([]);
      setConfirmPhrase("");
      setBackupConfirmed(false);
      void queryClient.invalidateQueries({
        queryKey: ["admin", "member-cleanup-candidates"],
      });
      void queryClient.invalidateQueries({ queryKey: ["admin", "members"] });
      modal.info({
        title: "실행 결과",
        content: (
          <pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>
            {JSON.stringify(data, null, 2)}
          </pre>
        ),
      });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const selectableRows = useMemo(
    () =>
      (candidatesQuery.data?.items ?? []).filter(
        (row) => !row.protected && !row.is_self && row.can_deactivate,
      ),
    [candidatesQuery.data],
  );

  const canExecute =
    selectedUserIds.length > 0 &&
    confirmPhrase === CONFIRM_PHRASE &&
    backupConfirmed;

  const openDrawer = () => {
    setDrawerOpen(true);
  };

  const loadCandidates = () => {
    setLoaded(true);
    setPreviewData(null);
  };

  return (
    <>
      <Card
        size="small"
        title="테스트 계정 정리 Preview"
        style={{ marginBottom: 16 }}
        extra={
          <Button onClick={openDrawer}>Preview 열기</Button>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          admin · kikicom 계정은 보호됩니다. 자동 실행하지 않으며, Preview 후
          확인 문구(`{CONFIRM_PHRASE}`)와 DB 백업 확인이 필요합니다.
        </Typography.Paragraph>
      </Card>

      <Drawer
        title="테스트 계정 정리 Preview"
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setLoaded(false);
          setPreviewData(null);
        }}
        size={720}
      >
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            title="Hard delete 금지"
            description="deactivate 또는 soft_delete만 가능합니다. 로드·Preview·Execute는 모두 수동으로 실행하세요."
          />

          <Space wrap>
            <Checkbox
              checked={includeDeleted}
              onChange={(event) => setIncludeDeleted(event.target.checked)}
            >
              삭제 포함 조회
            </Checkbox>
            <Button
              type="primary"
              onClick={loadCandidates}
              loading={candidatesQuery.isFetching && loaded}
            >
              후보 목록 불러오기
            </Button>
          </Space>

          {!loaded ? (
            <Typography.Text type="secondary">
              「후보 목록 불러오기」를 눌러야 API가 호출됩니다.
            </Typography.Text>
          ) : null}

          {candidatesQuery.error ? (
            <Alert
              type="error"
              showIcon
              title={toApiError(candidatesQuery.error).message}
            />
          ) : null}

          {loaded && candidatesQuery.data ? (
            <>
              <Typography.Text type="secondary">
                보호 계정:{" "}
                {(candidatesQuery.data.protected_usernames ?? []).join(", ")} ·
                후보 {candidatesQuery.data.candidate_count}명
              </Typography.Text>

              <Table<MemberCleanupCandidate>
                size="small"
                loading={candidatesQuery.isLoading}
                rowKey={(row) => String(row.user_id)}
                dataSource={candidatesQuery.data?.items ?? []}
                rowSelection={{
                  selectedRowKeys: selectedUserIds,
                  onChange: (keys) => setSelectedUserIds(keys as number[]),
                  getCheckboxProps: (row) => ({
                    disabled: row.protected || row.is_self || !row.can_deactivate,
                  }),
                }}
                pagination={{ pageSize: 10, showSizeChanger: false }}
                columns={[
                  { title: "ID", dataIndex: "user_id", width: 70 },
                  { title: "username", dataIndex: "username" },
                  {
                    title: "상태",
                    key: "status",
                    width: 120,
                    render: (_, row) => (
                      <Space size={4}>
                        {row.protected ? (
                          <Tag color="gold">protected</Tag>
                        ) : null}
                        {row.is_self ? <Tag color="blue">self</Tag> : null}
                        {!row.is_active ? <Tag>inactive</Tag> : null}
                        {row.deleted_at ? <Tag color="error">deleted</Tag> : null}
                      </Space>
                    ),
                  },
                  {
                    title: "refs",
                    dataIndex: "ref_counts",
                    render: (value: Record<string, number>) => (
                      <Typography.Text code style={{ fontSize: 11 }}>
                        {JSON.stringify(value)}
                      </Typography.Text>
                    ),
                  },
                  {
                    title: "권장",
                    dataIndex: "recommended_action",
                    width: 110,
                  },
                ]}
              />

              <Space wrap>
                <Select
                  style={{ width: 160 }}
                  value={mode}
                  onChange={setMode}
                  options={[
                    { value: "deactivate", label: "deactivate" },
                    { value: "soft_delete", label: "soft_delete" },
                  ]}
                />
                <Button
                  disabled={selectedUserIds.length === 0}
                  loading={previewMut.isPending}
                  onClick={() =>
                    previewMut.mutate({
                      user_ids: selectedUserIds,
                      mode,
                      confirm_phrase: CONFIRM_PHRASE,
                      backup_confirmed: backupConfirmed,
                    })
                  }
                >
                  Preview ({selectedUserIds.length})
                </Button>
              </Space>

              {previewData ? (
                <Alert
                  type="info"
                  showIcon
                  title="Preview 결과 (변경 없음)"
                  description={
                    <pre style={{ margin: 0, fontSize: 11, whiteSpace: "pre-wrap" }}>
                      {JSON.stringify(previewData, null, 2)}
                    </pre>
                  }
                />
              ) : null}

              <Input
                placeholder={`confirm_phrase: ${CONFIRM_PHRASE}`}
                value={confirmPhrase}
                onChange={(event) => setConfirmPhrase(event.target.value)}
              />
              <Checkbox
                checked={backupConfirmed}
                onChange={(event) => setBackupConfirmed(event.target.checked)}
              >
                DB 백업을 확인했습니다 (backup_confirmed)
              </Checkbox>

              <Button
                danger
                disabled={!canExecute}
                loading={executeMut.isPending}
                onClick={() => {
                  modal.confirm({
                    title: "테스트 계정 정리 실행",
                    content: `${selectedUserIds.length}명을 ${mode} 처리합니다. 계속할까요?`,
                    okButtonProps: { danger: true },
                    onOk: () =>
                      executeMut.mutateAsync({
                        user_ids: selectedUserIds,
                        mode,
                        confirm_phrase: CONFIRM_PHRASE,
                        backup_confirmed: true,
                      }),
                  });
                }}
              >
                Execute (확인 후)
              </Button>

              {selectableRows.length === 0 && !candidatesQuery.isLoading ? (
                <Typography.Text type="secondary">
                  선택 가능한 후보가 없습니다.
                </Typography.Text>
              ) : null}
            </>
          ) : null}
        </Space>
      </Drawer>
    </>
  );
}
