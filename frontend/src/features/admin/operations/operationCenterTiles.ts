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
}

export const OPERATION_CENTER_TILES: OperationCenterTile[] = [
  {
    id: "health",
    title: "Health Check",
    description: "API · DB · 컴포넌트 헬스",
    href: adminRoutes.monitoring,
    support: "live",
    apis: ["GET /health", "GET /version"],
  },
  {
    id: "scheduler",
    title: "Scheduler",
    description: "잡 목록 · 실행 · 히스토리",
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
    title: "Broker",
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
    title: "System Monitor",
    description: "시스템·리스크·품질 대시보드",
    href: adminRoutes.monitoring,
    support: "live",
    apis: ["GET /system/dashboard", "GET /dashboard/risk"],
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
    id: "logs",
    title: "Log Viewer",
    description: "감사 로그 (앱 로그 테일 없음)",
    href: adminRoutes.logs,
    support: "partial",
    apis: ["GET /audit/events"],
  },
  {
    id: "backup",
    title: "Backup",
    description: "백업 도구 점검 (웹 dump 없음)",
    href: adminRoutes.db,
    support: "partial",
    apis: ["GET /ops/backup/status"],
  },
  {
    id: "restore",
    title: "Restore",
    description: "웹 restore 미지원 — CLI 매뉴얼",
    href: adminRoutes.db,
    support: "planned",
    apis: ["TODO: POST /ops/backup/restore"],
  },
];
