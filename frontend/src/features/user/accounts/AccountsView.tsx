"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message as antdMessage,
} from "antd";
import { useMemo, useState } from "react";

import { PageContainer } from "@/components/common/PageContainer";
import type { UserAccount } from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { BrokerCredentialPanel } from "@/features/user/accounts/BrokerCredentialPanel";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export type AccountTypeFilter = "KIWOOM" | "UPBIT" | "PAPER";

const FILTER_META: Record<
  AccountTypeFilter,
  { title: string; description: string }
> = {
  KIWOOM: {
    title: "키움 계좌",
    description:
      "키움증권 연동 계좌 목록입니다. 실계좌 번호·Secret은 저장·표시하지 않습니다.",
  },
  UPBIT: {
    title: "업비트 계좌",
    description:
      "업비트 연동 계좌 목록입니다. API Key·Secret은 저장·표시하지 않습니다.",
  },
  PAPER: {
    title: "Paper 계좌",
    description:
      "모의투자(Paper Trading) 계좌 목록입니다. 실제 자금은 사용되지 않습니다.",
  },
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("ko-KR");
  } catch {
    return String(value);
  }
}

interface AccountsViewProps {
  /** 지정 시 해당 유형만 필터링해서 보여준다 (전체 계좌 화면은 미지정) */
  accountTypeFilter?: AccountTypeFilter;
}

/**
 * 내 계좌 화면 — 전체·키움·업비트·Paper 공용 컴포넌트.
 * accountTypeFilter로 목록·생성 폼을 필터링한다. (실제 API 재호출 없이 클라이언트 필터)
 */
export function AccountsView({ accountTypeFilter }: AccountsViewProps) {
  // App.useApp 대신 hooks — Next.js에서 테마 컨텍스트 경고 방지
  const [messageApi, messageContextHolder] = antdMessage.useMessage();
  const [modalApi, modalContextHolder] = Modal.useModal();
  const queryClient = useQueryClient();
  const [positionsAccountId, setPositionsAccountId] = useState<number | null>(
    null,
  );
  const [createForm] = Form.useForm();
  const [brokerForm] = Form.useForm();
  const [renameForm] = Form.useForm();
  const [credentialAccount, setCredentialAccount] =
    useState<UserAccount | null>(null);

  const accountsQuery = useQuery({
    queryKey: queryKeys.user.userAccounts({ include_inactive: true }),
    queryFn: () => userApi.listUserAccounts({ include_inactive: true }),
  });

  const accounts = useMemo(() => {
    const all = accountsQuery.data?.items ?? [];
    return accountTypeFilter
      ? all.filter((row) => row.account_type === accountTypeFilter)
      : all;
  }, [accountsQuery.data, accountTypeFilter]);

  const positionsQuery = useQuery({
    queryKey: queryKeys.user.paperPositions(positionsAccountId ?? 0),
    queryFn: () => userApi.getPaperPositions(positionsAccountId!),
    enabled: positionsAccountId !== null && positionsAccountId > 0,
  });

  const invalidateAccounts = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["user", "accounts"],
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.myPaperAccount(),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.user.paperAccounts(),
    });
  };

  const createPaper = useMutation({
    mutationFn: (values: {
      account_name: string;
      initial_cash: number;
    }) =>
      userApi.createUserAccount({
        account_type: "PAPER",
        account_name: values.account_name,
        initial_cash: values.initial_cash,
      }),
    onSuccess: async () => {
      messageApi.success("Paper 계좌를 생성했습니다.");
      createForm.resetFields();
      await invalidateAccounts();
    },
    onError: (error) => messageApi.error(toApiError(error).message),
  });

  const createBroker = useMutation({
    mutationFn: (values: {
      account_type: string;
      account_name: string;
      account_number: string;
    }) =>
      userApi.createUserAccount({
        account_type: values.account_type,
        account_name: values.account_name,
        account_number: values.account_number,
      }),
    onSuccess: async () => {
      messageApi.success("Broker 계좌 연결을 등록했습니다.");
      brokerForm.resetFields();
      await invalidateAccounts();
    },
    onError: (error) => messageApi.error(toApiError(error).message),
  });

  const runAction = useMutation({
    mutationFn: async (payload: {
      action:
        | "default"
        | "connect"
        | "disconnect"
        | "sync"
        | "delete"
        | "rename";
      account: UserAccount;
      account_name?: string;
    }) => {
      const params = { account_type: payload.account.account_type };
      switch (payload.action) {
        case "default":
          return userApi.setDefaultUserAccount(
            payload.account.account_id,
            params,
          );
        case "connect":
          return userApi.connectUserAccount(
            payload.account.account_id,
            params,
          );
        case "disconnect":
          return userApi.disconnectUserAccount(
            payload.account.account_id,
            params,
          );
        case "sync":
          return userApi.syncUserAccount(payload.account.account_id, params);
        case "delete":
          return userApi.deleteUserAccount(
            payload.account.account_id,
            params,
          );
        case "rename":
          return userApi.updateUserAccount(payload.account.account_id, {
            account_type: payload.account.account_type,
            account_name: payload.account_name,
          });
        default:
          throw new Error("unknown action");
      }
    },
    onSuccess: async (_data, variables) => {
      const labels: Record<string, string> = {
        default: "기본 계좌로 지정했습니다.",
        connect: "연결했습니다.",
        disconnect: "연결을 해제했습니다.",
        sync: "동기화했습니다.",
        delete: "삭제(또는 연결 해제)했습니다.",
        rename: "이름을 수정했습니다.",
      };
      messageApi.success(labels[variables.action] ?? "완료");
      await invalidateAccounts();
    },
    onError: (error) => messageApi.error(toApiError(error).message),
  });

  const confirmDelete = (account: UserAccount) => {
    const isPaper = account.account_type === "PAPER";
    modalApi.confirm({
      title: isPaper ? "Paper 계좌 비활성화" : "Broker 연결 해제",
      content: isPaper
        ? `"${account.account_name}" 계좌를 비활성화합니다. (소프트 삭제)`
        : `"${account.account_name}" 플랫폼 연결만 제거합니다. 실계좌는 삭제되지 않습니다.`,
      okText: isPaper ? "비활성화" : "연결 제거",
      okButtonProps: { danger: true },
      onOk: () =>
        runAction.mutateAsync({ action: "delete", account }),
    });
  };

  const openRename = (account: UserAccount) => {
    // Modal.confirm content 마운트 전 setFieldsValue 금지 — initialValues 사용
    modalApi.confirm({
      title: "계좌 이름 수정",
      content: (
        <Form
          key={`rename-${account.account_id}`}
          form={renameForm}
          layout="vertical"
          style={{ marginTop: 12 }}
          initialValues={{ account_name: account.account_name }}
        >
          <Form.Item
            name="account_name"
            label="별칭"
            rules={[{ required: true, message: "이름을 입력하세요" }]}
          >
            <Input maxLength={100} />
          </Form.Item>
        </Form>
      ),
      onOk: async () => {
        const values = await renameForm.validateFields();
        await runAction.mutateAsync({
          action: "rename",
          account,
          account_name: values.account_name,
        });
      },
    });
  };

  const paperOptions = useMemo(
    () =>
      accounts
        .filter((row) => row.account_type === "PAPER" && row.is_active)
        .map((row) => ({
          value: row.account_id,
          label: `${row.account_name} (#${row.account_id})`,
        })),
    [accounts],
  );

  const meta = accountTypeFilter ? FILTER_META[accountTypeFilter] : null;
  const title = meta?.title ?? "내 계좌";
  const description =
    meta?.description ??
    "회원별 Paper·Broker 계좌 연결을 관리합니다. 실계좌 번호·Secret은 저장·표시하지 않습니다.";

  const showPaperCreate = !accountTypeFilter || accountTypeFilter === "PAPER";
  const showBrokerConnect =
    !accountTypeFilter ||
    accountTypeFilter === "KIWOOM" ||
    accountTypeFilter === "UPBIT";
  const brokerTypeOptions =
    accountTypeFilter === "KIWOOM" || accountTypeFilter === "UPBIT"
      ? [{ value: accountTypeFilter, label: accountTypeFilter }]
      : [
          { value: "KIWOOM", label: "KIWOOM" },
          { value: "UPBIT", label: "UPBIT" },
        ];
  const showPositions = !accountTypeFilter || accountTypeFilter === "PAPER";

  const pausedOrReviewAccounts = useMemo(
    () =>
      accounts.filter(
        (row) =>
          row.trading_paused === true ||
          row.recovery_review_required === true,
      ),
    [accounts],
  );

  const rateLimitedAccounts = useMemo(
    () =>
      accounts.filter(
        (row) =>
          row.account_type === "UPBIT" &&
          (row.upbit_api_status === "RATE_LIMITED" ||
            row.upbit_api_status === "ADMIN_REVIEW_REQUIRED"),
      ),
    [accounts],
  );

  return (
    <PageContainer title={title} description={description}>
      {messageContextHolder}
      {modalContextHolder}
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {!accountTypeFilter ? (
          <Alert
            type="info"
            showIcon
            title="키움 실연동 안내"
            description="키움 OpenAPI는 현재 서버 공용 인증을 사용합니다. 회원별로는 계좌 소유권 매핑만 관리하며, Client Secret·Access Token은 저장하지 않습니다."
          />
        ) : null}

        {pausedOrReviewAccounts.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            title="Recovery 검토·거래 일시중지"
            description={
              pausedOrReviewAccounts[0]?.recovery_user_message ??
              "관리자 확인이 필요합니다. 해당 계좌 거래가 일시중지되었을 수 있습니다."
            }
          />
        ) : null}

        {rateLimitedAccounts.length > 0 ? (
          <Alert
            type="info"
            showIcon
            title="Upbit 요청 제한"
            description={
              rateLimitedAccounts[0]?.upbit_rate_limit_message ??
              "일시적 요청 제한 또는 동기화 지연이 있을 수 있습니다."
            }
          />
        ) : null}

        {accountsQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(accountsQuery.error).message}
          />
        ) : null}

        <Card title="계좌 목록" size="small" loading={accountsQuery.isLoading}>
          <Table<UserAccount>
            size="small"
            rowKey={(row) => `${row.account_type}-${row.account_id}`}
            dataSource={accounts}
            pagination={false}
            locale={{
              emptyText: accountTypeFilter
                ? "연결된 계좌가 없습니다. 아래에서 계좌를 먼저 연결해 주세요."
                : "연결된 계좌가 없습니다. 아래에서 계좌를 먼저 연결해 주세요.",
            }}
            columns={[
              {
                title: "유형",
                dataIndex: "account_type",
                width: 90,
                render: (value: string) => <Tag>{value}</Tag>,
              },
              {
                title: "별칭",
                dataIndex: "account_name",
              },
              {
                title: "마스킹 번호",
                dataIndex: "masked_account_number",
                render: (value: string | null) => value ?? "-",
              },
              {
                title: "거래",
                key: "recovery_trade",
                width: 120,
                render: (_: unknown, row: UserAccount) => {
                  if (row.trading_paused) {
                    return <Tag color="red">일시중지</Tag>;
                  }
                  if (row.recovery_review_required) {
                    return <Tag color="orange">검토 필요</Tag>;
                  }
                  if (row.upbit_api_status === "ADMIN_REVIEW_REQUIRED") {
                    return <Tag color="orange">관리자 확인</Tag>;
                  }
                  if (row.upbit_api_status === "RATE_LIMITED") {
                    return <Tag color="gold">요청 제한</Tag>;
                  }
                  return <Tag>정상</Tag>;
                },
              },
              {
                title: "기본",
                dataIndex: "is_default",
                width: 70,
                render: (value: boolean) =>
                  value ? <Tag color="blue">기본</Tag> : "-",
              },
              {
                title: "연결",
                dataIndex: "connection_status",
                width: 110,
              },
              {
                title: "활성",
                dataIndex: "is_active",
                width: 70,
                render: (value: boolean) =>
                  value ? <Tag color="green">Y</Tag> : <Tag>N</Tag>,
              },
              {
                title: "최근 동기화",
                dataIndex: "last_synced_at",
                render: formatDate,
              },
              {
                title: "작업",
                key: "actions",
                width: 360,
                render: (_: unknown, row: UserAccount) => (
                  <Space wrap size={4}>
                    <Button size="small" onClick={() => openRename(row)}>
                      이름
                    </Button>
                    <Button
                      size="small"
                      disabled={row.is_default || !row.is_active}
                      onClick={() =>
                        runAction.mutate({ action: "default", account: row })
                      }
                    >
                      기본
                    </Button>
                    <Button
                      size="small"
                      onClick={() =>
                        runAction.mutate({ action: "connect", account: row })
                      }
                    >
                      연결
                    </Button>
                    {row.account_type === "KIWOOM" ||
                    row.account_type === "UPBIT" ? (
                      <Button
                        size="small"
                        type="primary"
                        ghost
                        onClick={() => setCredentialAccount(row)}
                      >
                        API Credential
                      </Button>
                    ) : null}
                    <Button
                      size="small"
                      onClick={() =>
                        runAction.mutate({ action: "disconnect", account: row })
                      }
                    >
                      해제
                    </Button>
                    <Button
                      size="small"
                      onClick={() =>
                        runAction.mutate({ action: "sync", account: row })
                      }
                    >
                      동기화
                    </Button>
                    {row.account_type === "PAPER" ? (
                      <Button
                        size="small"
                        onClick={() => setPositionsAccountId(row.account_id)}
                      >
                        포지션
                      </Button>
                    ) : null}
                    <Button
                      size="small"
                      danger
                      onClick={() => confirmDelete(row)}
                    >
                      삭제
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        </Card>

        {showPaperCreate ? (
          <Card title="Paper 계좌 생성" size="small">
            <Form
              form={createForm}
              layout="inline"
              onFinish={(values) => createPaper.mutate(values)}
              initialValues={{ initial_cash: 10_000_000 }}
            >
              <Form.Item
                name="account_name"
                rules={[{ required: true, message: "계좌명" }]}
              >
                <Input placeholder="모의 계좌명" />
              </Form.Item>
              <Form.Item
                name="initial_cash"
                rules={[{ required: true, message: "초기 현금" }]}
              >
                <InputNumber min={1} style={{ width: 160 }} />
              </Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                loading={createPaper.isPending}
              >
                생성
              </Button>
            </Form>
          </Card>
        ) : null}

        {showBrokerConnect ? (
          <Card title="Broker 계좌 연결" size="small">
            <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
              계좌번호는 해시·마스킹만 저장됩니다. API Key·Secret은 계좌 등록 후
              「API Credential」에서 암호화 등록하세요.
            </Typography.Paragraph>
            <Form
              form={brokerForm}
              layout="inline"
              onFinish={(values) => createBroker.mutate(values)}
              initialValues={{
                account_type: brokerTypeOptions[0]?.value ?? "KIWOOM",
              }}
            >
              <Form.Item name="account_type" rules={[{ required: true }]}>
                <Select
                  style={{ width: 120 }}
                  disabled={brokerTypeOptions.length === 1}
                  options={brokerTypeOptions}
                />
              </Form.Item>
              <Form.Item
                name="account_name"
                rules={[{ required: true, message: "별칭" }]}
              >
                <Input placeholder="별칭" />
              </Form.Item>
              <Form.Item
                name="account_number"
                rules={[{ required: true, message: "계좌번호" }]}
              >
                <Input placeholder="계좌번호 (마스킹 저장)" />
              </Form.Item>
              <Button
                type="default"
                htmlType="submit"
                loading={createBroker.isPending}
              >
                연결 등록
              </Button>
            </Form>
          </Card>
        ) : null}

        {showPositions ? (
          <Card title="계좌별 포지션 (Paper)" size="small">
            <Space style={{ marginBottom: 12 }}>
              <Select
                style={{ width: 280 }}
                placeholder="Paper 계좌 선택"
                options={paperOptions}
                value={positionsAccountId ?? undefined}
                onChange={(value: number) => setPositionsAccountId(value)}
                allowClear
                onClear={() => setPositionsAccountId(null)}
              />
            </Space>
            {positionsAccountId ? (
              positionsQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(positionsQuery.error).message}
                />
              ) : (
                <pre style={{ margin: 0, fontSize: 12, overflow: "auto" }}>
                  {JSON.stringify(positionsQuery.data ?? [], null, 2)}
                </pre>
              )
            ) : (
              <Typography.Text type="secondary">
                Paper 계좌를 선택하면 포지션을 조회합니다.
              </Typography.Text>
            )}
          </Card>
        ) : null}
      </Space>

      {credentialAccount ? (
        <BrokerCredentialPanel
          account={credentialAccount}
          open={credentialAccount !== null}
          onClose={() => setCredentialAccount(null)}
        />
      ) : null}
    </PageContainer>
  );
}
