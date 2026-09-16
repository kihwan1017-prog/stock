import { adminRoutes } from "@/config/routes";

/** STEP51 운영센터 — 상세 화면 딥링크 타일 */
export interface OperationCenterTile {
  id: string;
  title: string;
  description: string;
  href: string;
  /** live | partial | planned */
  support: "live" | "partial" | "planned";
  apis: string[];
  /** planned 타일 — 비활성 버튼에 표시할 사유 */
  plannedReason?: string;
  /** planned 타일 — 관련 화면 링크 (없으면 href 사용) */
  relatedHref?: string;
}

export const OPERATION_CENTER_TILES: OperationCenterTile[] = [
  {
    id: "health",
    title: "시스템 모니터링",
    description: "인프라 health · live/ready · 상세는 이 화면에서 확인",
    href: adminRoutes.monitoring,
    support: "live",
    apis: ["GET /health", "GET /system/monitoring/overview"],
  },
  {
    id: "preflight",
    title: "Pre-flight Check",
    description: "LIVE ON 전 운영 조건 자동 점검",
    href: adminRoutes.operationsPreflight,
    support: "live",
    apis: ["GET /admin/runtime/preflight"],
  },
  {
    id: "scheduler",
    title: "스케줄러",
    description: "잡 목록 · 실행은 스케줄러 화면에서만",
    href: adminRoutes.scheduler,
    support: "live",
    apis: ["GET /jobs", "POST /jobs/{name}/execute", "GET /jobs/history"],
  },
  {
    id: "batch",
    title: "Batch",
    description: "파이프라인 · 일일 리포트",
    href: adminRoutes.batch,
    support: "live",
    apis: ["GET /pipelines/latest", "GET /daily-reports"],
  },
  {
    id: "broker",
    title: "거래소/증권사",
    description: "키움 · 업비트 · 계좌 연동",
    href: adminRoutes.kiwoom,
    support: "live",
    apis: [
      "GET /kiwoom/configuration",
      "GET /broker/account",
      "GET /upbit/markets",
    ],
  },
  {
    id: "postgres",
    title: "PostgreSQL",
    description: "DB 상태 · 마이그레이션 · 테이블",
    href: adminRoutes.db,
    support: "live",
    apis: [
      "GET /ops/db/status",
      "GET /ops/db/migration-status",
      "GET /ops/db/tables",
    ],
  },
  {
    id: "monitor",
    title: "거래 운영 현황",
    description: "조회 전용 · Runtime/주문/리스크 요약 (제어 없음)",
    href: adminRoutes.operationsDashboard,
    support: "live",
    apis: ["GET /admin/operations-dashboard/overview"],
  },
  {
    id: "environment",
    title: "Environment",
    description: "환경·시스템 설정",
    href: adminRoutes.envSettings,
    support: "live",
    apis: ["GET/PUT /settings"],
  },
  {
    id: "live-activation",
    title: "계좌 LIVE 제어",
    description: "LIVE/ARM/Trading Scheduler는 업비트 계좌 화면에서 수행",
    href: adminRoutes.upbit,
    support: "live",
    apis: [
      "PUT /admin/live-order/accounts/{id}",
      "POST /admin/live-order/accounts/{id}/arm",
    ],
  },
  {
    id: "runtime",
    title: "자동매매 Runtime",
    description: "Scope Runtime · Realtime Hub 제어 (주문 관리 아님)",
    href: adminRoutes.trading,
    support: "live",
    apis: ["GET /admin/runtimes", "GET realtime-hub/scopes"],
  },
  {
    id: "recovery",
    title: "장애 복구",
    description: "Broker Recovery · Conflict · Lock — HIGH 제어 전용 화면",
    href: adminRoutes.recovery,
    support: "live",
    apis: ["GET/POST /admin/recovery"],
  },
  {
    id: "risk",
    title: "리스크 관리",
    description: "Kill Switch · 리스크 설정 (이 런치패드에서 제어하지 않음)",
    href: adminRoutes.risk,
    support: "live",
    apis: ["GET /risk/kill-switch"],
  },
  {
    id: "orders",
    title: "주문·Outbox",
    description: "주문 내역 · Outbox 상세",
    href: adminRoutes.orders,
    support: "live",
    apis: ["GET /order-outbox"],
  },
  {
    id: "settlement",
    title: "Account Settlement",
    description: "EOD 정산 · 불일치 · Manual Review",
    href: adminRoutes.batch,
    support: "live",
    apis: [
      "GET /admin/settlements",
      "GET /admin/settlements/health",
      "POST /admin/settlements/{id}/retry",
    ],
  },
  {
    id: "logs",
    title: "Log Tail",
    description: "앱 로그 파일 테일 — API 미구현",
    href: adminRoutes.logs,
    relatedHref: adminRoutes.logs,
    support: "planned",
    plannedReason: "앱 로그 테일 API 미구현",
    apis: ["TODO: GET /ops/logs/tail", "GET /audit/events (감사 로그만)"],
  },
  {
    id: "backup",
    title: "Backup Dump",
    description: "웹에서 pg_dump 실행 — API 미구현",
    href: adminRoutes.db,
    relatedHref: adminRoutes.db,
    support: "planned",
    plannedReason: "웹 Backup dump API 미구현",
    apis: ["GET /ops/backup/status", "TODO: POST /ops/backup/dump"],
  },
  {
    id: "telegram",
    title: "Telegram",
    description: "Bot 상태 · 알림 이벤트 · 운영 명령",
    href: adminRoutes.telegram,
    support: "live",
    apis: [
      "GET /notification/status",
      "POST /notification/test",
      "GET /telegram/ops/status",
    ],
  },
  {
    id: "ollama",
    title: "Ollama",
    description: "로컬 LLM 상태 · 모델",
    href: adminRoutes.ollama,
    support: "live",
    apis: ["GET /ollama/status", "GET /ollama/models"],
  },
  {
    id: "restore",
    title: "Restore",
    description: "웹 restore 미지원 — CLI 매뉴얼",
    href: adminRoutes.db,
    relatedHref: adminRoutes.db,
    support: "planned",
    plannedReason: "웹 Restore API 미구현",
    apis: ["TODO: POST /ops/backup/restore"],
  },
];
