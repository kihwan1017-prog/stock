"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Switch,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import {
  buildPaperAccountDeleteConfirmContent,
  canShowPaperAccountDeleteButton,
} from "@/features/admin/accounts/paperAccountDelete";
import { AdminBrokerCredentialCard } from "@/features/admin/accounts/AdminBrokerCredentialCard";
import { AdminUpbitLiveUbaPanel } from "@/features/admin/accounts/AdminUpbitLiveUbaPanel";
import {
  buildPaperAccountUpdatePayload,
  canShowPaperAccountEditButton,
  initialCashDisabledReason,
  resolveCanEditInitialCash,
  validatePaperAccountUpdateForm,
  type PaperAccountRecord,
} from "@/features/admin/accounts/paperAccountUpdate";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { useAuth } from "@/features/auth/hooks/useAuth";
import {
  hasAnyRole,
  hasPermission,
} from "@/features/auth/utils/permissions";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminAccountsPage() {
  const { message, modal } = App.useApp();
  const { user } = useAuth();
  const isAdmin = hasAnyRole(user, "admin");
  const canWrite = hasPermission(user, "trading:write");
  const queryClient = useQueryClient();
  const [paperAccountId, setPaperAccountId] = useState<number | null>(null);
  const [editTargetId, setEditTargetId] = useState<number | null>(null);
  const [kiwoomUbaId, setKiwoomUbaId] = useState<number | null>(null);
  const [editForm] = Form.useForm<{
    account_name: string;
    is_active: boolean;
    is_default: boolean;
    initial_cash: number;
  }>();

  const broker = useQuery({
    queryKey: queryKeys.admin.brokerAccount(),
    queryFn: adminApi.getBrokerAccount,
  });
  const paperAccounts = useQuery({
    queryKey: queryKeys.admin.paperAccounts(),
    queryFn: () => adminApi.listPaperAccounts({ limit: 100 }),
  });
  const selectedId = paperAccountId ?? 0;
  const positions = useQuery({
    queryKey: queryKeys.admin.paperPositions(selectedId),
    queryFn: () => adminApi.getPaperPositions(selectedId),
    enabled: selectedId > 0,
  });
  const liveHistory = useQuery({
    queryKey: queryKeys.admin.liveTransitionHistory(),
    queryFn: adminApi.getLiveTransitionHistory,
  });
  const editDetail = useQuery({
    queryKey: queryKeys.admin.paperAccount(editTargetId ?? 0),
    queryFn: () => adminApi.getPaperAccount(editTargetId!),
    enabled: editTargetId !== null && editTargetId > 0,
  });

  const accountRows = useMemo(
    () => extractRows(paperAccounts.data) as Record<string, unknown>[],
    [paperAccounts.data],
  );

  const editAccount = editDetail.data as PaperAccountRecord | undefined;
  const canEditInitialCash = editAccount
    ? resolveCanEditInitialCash(editAccount)
    : false;
  const cashDisabledReason = initialCashDisabledReason(canEditInitialCash);

  const createPaper = useMutation({
    mutationFn: adminApi.createPaperAccount,
    onSuccess: (data) => {
      message.success("페이퍼 계좌 생성 완료");
      const created = data as { account_id?: number };
      if (created.account_id) {
        setPaperAccountId(Number(created.account_id));
      }
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.paperAccounts(),
      });
    },
    onError: (err) => message.error(toApiError(err).message),
  });
  const updatePaper = useMutation({
    mutationFn: ({
      accountId,
      body,
    }: {
      accountId: number;
      body: adminApi.PaperAccountUpdateBody;
    }) => adminApi.updatePaperAccount(accountId, body),
    onSuccess: () => {
      message.success("모의계좌가 수정되었습니다.");
      setEditTargetId(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.paperAccounts(),
      });
    },
    onError: (err) => message.error(toApiError(err).message),
  });
  const deletePaper = useMutation({
    mutationFn: adminApi.deletePaperAccount,
    onSuccess: (data) => {
      message.success(
        data.has_trading_history
          ? "Soft Delete 완료 (주문/체결 이력 보존)"
          : "Soft Delete 완료",
      );
      if (paperAccountId === data.account_id) {
        setPaperAccountId(null);
      }
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.paperAccounts(),
      });
    },
    onError: (err) => message.error(toApiError(err).message),
  });
  const syncKiwoom = useMutation({
    mutationFn: (id: number) => adminApi.syncKiwoomAccount(id),
    onSuccess: () => {
      message.success("키움 계좌 동기화 요청 완료 (UBA Binding)");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.brokerAccount(),
      });
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const positionRows = extractRows(positions.data);

  const openEdit = (row: Record<string, unknown>) => {
    const accountId = Number(row.account_id);
    if (!canShowPaperAccountEditButton(canWrite, accountId)) {
      message.error("수정 권한이 없습니다.");
      return;
    }
    setEditTargetId(accountId);
  };

  const closeEdit = () => {
    if (updatePaper.isPending) return;
    setEditTargetId(null);
  };

  const submitEdit = async () => {
    if (!editAccount || editTargetId === null || updatePaper.isPending) {
      return;
    }
    try {
      const values = await editForm.validateFields();
      const formError = validatePaperAccountUpdateForm({
        account_name: values.account_name,
        initial_cash: values.initial_cash,
        canEditInitialCash,
      });
      if (formError) {
        message.error(formError);
        return;
      }
      const body = buildPaperAccountUpdatePayload(editAccount, values);
      if (Object.keys(body).length === 0) {
        message.info("변경된 항목이 없습니다.");
        return;
      }
      await updatePaper.mutateAsync({ accountId: editTargetId, body });
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) {
        return;
      }
      message.error(toApiError(err).message);
    }
  };

  const confirmDelete = (row: Record<string, unknown>) => {
    const accountId = Number(row.account_id);
    if (!canShowPaperAccountDeleteButton(isAdmin, accountId)) {
      message.error("관리자만 Soft Delete 할 수 있습니다.");
      return;
    }
    modal.confirm({
      title: "모의계좌 Soft Delete",
      content: buildPaperAccountDeleteConfirmContent({
        account_id: accountId,
        account_name: String(row.account_name ?? ""),
        is_default: Boolean(row.is_default),
      }),
      okText: "Soft Delete",
      okType: "danger",
      cancelText: "취소",
      onOk: () => deletePaper.mutateAsync(accountId),
    });
  };

  return (
    <AdminPageShell
      title="계좌관리"
      description="Paper CRUD + UPBIT LIVE UBA CRUD / Credential (실주문·ARM 없음)"
      extra={
        <Space wrap>
          <InputNumber
            placeholder="키움 UBA ID"
            min={1}
            value={kiwoomUbaId ?? undefined}
            onChange={(v) => setKiwoomUbaId(typeof v === "number" ? v : null)}
          />
          <PermissionButton
            permission="trading:write"
            loading={syncKiwoom.isPending}
            disabled={kiwoomUbaId == null}
            onClick={() =>
              kiwoomUbaId != null && syncKiwoom.mutate(kiwoomUbaId)
            }
          >
            키움 계좌 동기화
          </PermissionButton>
          <Button onClick={() => void broker.refetch()}>브로커 새로고침</Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Soft Delete는 관리자만 가능합니다. 수정은 trading:write (관리자 포함).
          초기 자산은 거래 이력이 없을 때만 변경할 수 있습니다.
        </Typography.Paragraph>

        <AdminUpbitLiveUbaPanel />

        <AdminJsonCard
          title="GET /broker/account (Paper 스냅샷)"
          loading={broker.isLoading}
          error={broker.error ? toApiError(broker.error) : null}
          data={broker.data}
        />

        <Form
          layout="inline"
          onFinish={(v: { account_name: string; initial_cash: number }) =>
            createPaper.mutate(v)
          }
          style={{ marginBottom: 8 }}
        >
          <Form.Item
            name="account_name"
            rules={[{ required: true, message: "계좌명 필요" }]}
          >
            <Input placeholder="account_name" />
          </Form.Item>
          <Form.Item
            name="initial_cash"
            rules={[{ required: true }]}
            initialValue={10_000_000}
          >
            <InputNumber min={1} placeholder="initial_cash" style={{ width: 160 }} />
          </Form.Item>
          <PermissionButton
            permission="trading:write"
            type="primary"
            htmlType="submit"
            loading={createPaper.isPending}
          >
            페이퍼 계좌 등록
          </PermissionButton>
        </Form>

        <AdminDataTable
          title="GET /paper-accounts (deleted_at IS NULL)"
          loading={paperAccounts.isLoading}
          error={paperAccounts.error ? toApiError(paperAccounts.error) : null}
          rowKey={(r) => cell(r.account_id ?? JSON.stringify(r))}
          columns={[
            { title: "account_id", dataIndex: "account_id", sorter: true },
            { title: "name", dataIndex: "account_name" },
            { title: "cash", dataIndex: "available_cash" },
            { title: "currency", dataIndex: "currency_code" },
            {
              title: "활성",
              dataIndex: "is_active",
              render: (value: boolean) => (value ? "Y" : "N"),
            },
            {
              title: "기본",
              dataIndex: "is_default",
              render: (value: boolean) => (value ? "Y" : "N"),
            },
            {
              title: "작업",
              key: "actions",
              render: (_, row) => (
                <Space size={4} wrap>
                  <Button
                    size="small"
                    onClick={() => setPaperAccountId(Number(row.account_id))}
                  >
                    포지션
                  </Button>
                  {canShowPaperAccountEditButton(canWrite, row.account_id) ? (
                    <Button size="small" onClick={() => openEdit(row)}>
                      수정
                    </Button>
                  ) : null}
                  {canShowPaperAccountDeleteButton(isAdmin, row.account_id) ? (
                    <Button
                      size="small"
                      danger
                      loading={deletePaper.isPending}
                      onClick={() => confirmDelete(row)}
                    >
                      삭제
                    </Button>
                  ) : null}
                </Space>
              ),
            },
          ]}
          dataSource={accountRows}
        />

        {selectedId > 0 ? (
          <AdminDataTable
            title={`GET /paper-accounts/${selectedId}/positions`}
            loading={positions.isLoading}
            error={positions.error ? toApiError(positions.error) : null}
            rowKey={(r) => cell(r.symbol ?? r.position_id ?? JSON.stringify(r))}
            columns={[
              { title: "심볼", dataIndex: "symbol", sorter: true },
              { title: "수량", dataIndex: "quantity" },
              { title: "평균단가", dataIndex: "average_entry_price" },
              {
                title: "원본",
                render: (_, row) => cell(row),
              },
            ]}
            dataSource={positionRows}
          />
        ) : null}

        <AdminJsonCard
          title="GET /broker/live-transition/history"
          loading={liveHistory.isLoading}
          error={liveHistory.error ? toApiError(liveHistory.error) : null}
          data={liveHistory.data}
        />
        <AdminBrokerCredentialCard />
      </Space>

      <Modal
        title={`모의계좌 수정 #${editTargetId ?? ""}`}
        open={editTargetId !== null}
        onCancel={closeEdit}
        okText="저장"
        cancelText="취소"
        confirmLoading={updatePaper.isPending}
        okButtonProps={{ disabled: updatePaper.isPending || editDetail.isLoading }}
        onOk={() => void submitEdit()}
        // destroyOnHidden 없이 forceRender — Form·useForm 항상 연결
        forceRender
      >
        {editDetail.isLoading ? (
          <Typography.Text>불러오는 중...</Typography.Text>
        ) : null}
        {editDetail.error ? (
          <Typography.Text type="danger">
            {toApiError(editDetail.error).message}
          </Typography.Text>
        ) : null}
        <Form
          key={
            editAccount
              ? `edit-${editAccount.account_id}-${editAccount.updated_at ?? ""}`
              : "edit-empty"
          }
          form={editForm}
          layout="vertical"
          disabled={updatePaper.isPending || !editAccount}
          style={{ display: editAccount ? undefined : "none" }}
          initialValues={
            editAccount
              ? {
                  account_name: editAccount.account_name,
                  is_active: Boolean(editAccount.is_active),
                  is_default: Boolean(editAccount.is_default),
                  initial_cash: Number(editAccount.initial_cash),
                }
              : undefined
          }
        >
            <Form.Item label="계좌 ID">
              <Input
                value={editAccount ? String(editAccount.account_id) : ""}
                disabled
              />
            </Form.Item>
            <Form.Item label="소유자 user_id">
              <Input
                value={editAccount ? String(editAccount.user_id ?? "-") : ""}
                disabled
              />
            </Form.Item>
            <Form.Item
              name="account_name"
              label="계좌명"
              rules={[
                { required: true, message: "계좌명을 입력하세요" },
                { max: 100, message: "최대 100자" },
              ]}
            >
              <Input maxLength={100} />
            </Form.Item>
            <Form.Item
              name="initial_cash"
              label="초기 자산"
              extra={cashDisabledReason ?? undefined}
              rules={
                canEditInitialCash
                  ? [{ required: true, message: "초기 자산을 입력하세요" }]
                  : undefined
              }
            >
              <InputNumber
                min={1}
                style={{ width: "100%" }}
                disabled={!canEditInitialCash}
              />
            </Form.Item>
            <Form.Item label="가용 현금 / 실현손익">
              <Typography.Text type="secondary">
                cash={String(editAccount?.available_cash ?? "-")} / PnL=
                {String(editAccount?.realized_profit_loss ?? "-")} (수정 불가)
              </Typography.Text>
            </Form.Item>
            <Form.Item
              name="is_active"
              label="사용 여부"
              valuePropName="checked"
            >
              <Switch checkedChildren="활성" unCheckedChildren="비활성" />
            </Form.Item>
            <Form.Item
              name="is_default"
              label="기본 계좌"
              valuePropName="checked"
            >
              <Switch checkedChildren="기본" unCheckedChildren="일반" />
            </Form.Item>
          </Form>
      </Modal>
    </AdminPageShell>
  );
}
