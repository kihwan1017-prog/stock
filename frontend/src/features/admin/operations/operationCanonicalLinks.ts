import { adminRoutes } from "@/config/routes";

/** M4-A: READ-only 교차 이동. mutation proxy 금지. */
export const OPERATION_CANONICAL_LINKS = [
  {
    id: "monitoring",
    label: "시스템 모니터링",
    href: adminRoutes.monitoring,
  },
  {
    id: "ops-dashboard",
    label: "거래 운영 현황",
    href: adminRoutes.operationsDashboard,
  },
  {
    id: "trading-runtime",
    label: "자동매매 Runtime",
    href: adminRoutes.trading,
  },
  {
    id: "preflight",
    label: "Pre-flight",
    href: adminRoutes.operationsPreflight,
  },
  {
    id: "scheduler",
    label: "스케줄러",
    href: adminRoutes.scheduler,
  },
  {
    id: "orders",
    label: "주문·Outbox",
    href: adminRoutes.orders,
  },
  {
    id: "risk",
    label: "리스크 관리",
    href: adminRoutes.risk,
  },
  {
    id: "recovery",
    label: "장애 복구",
    href: adminRoutes.recovery,
  },
  {
    id: "live-arm",
    label: "계좌 LIVE 제어",
    href: adminRoutes.upbit,
  },
] as const;
