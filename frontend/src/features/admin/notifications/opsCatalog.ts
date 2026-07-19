/**
 * STEP54 — 알림 이벤트 · Telegram 운영 명령 카탈로그
 * Discord는 범위 밖.
 */

export type NotificationEventSupport =
  | "live"
  | "partial"
  | "planned";

export interface NotificationEventSpec {
  id: string;
  label: string;
  description: string;
  support: NotificationEventSupport;
  related?: string[];
}

/** STEP54 NotificationEventType */
export const NOTIFICATION_EVENT_CATALOG: NotificationEventSpec[] = [
  {
    id: "SYSTEM_START",
    label: "시스템 시작",
    description: "API Lifecycle startup",
    support: "live",
    related: ["ApplicationLifecycle.startup"],
  },
  {
    id: "SYSTEM_STOP",
    label: "시스템 종료",
    description: "API Lifecycle shutdown",
    support: "live",
    related: ["ApplicationLifecycle.shutdown"],
  },
  {
    id: "ORDER_SUBMITTED",
    label: "주문 제출",
    description: "주문 제출 이벤트 (Publisher)",
    support: "partial",
  },
  {
    id: "ORDER_FILLED",
    label: "주문 체결",
    description: "체결 이벤트 (Publisher)",
    support: "partial",
  },
  {
    id: "ORDER_REJECTED",
    label: "주문 거부",
    description: "거부 이벤트 (Publisher)",
    support: "partial",
  },
  {
    id: "STOP_LOSS",
    label: "손절",
    description: "ExitMonitor → Publisher → Telegram",
    support: "live",
  },
  {
    id: "TAKE_PROFIT",
    label: "익절",
    description: "ExitMonitor → Publisher → Telegram",
    support: "live",
  },
  {
    id: "TRAILING_STOP",
    label: "트레일링 스톱",
    description: "ExitMonitor → Publisher → Telegram",
    support: "live",
  },
  {
    id: "RELATIVE_LOSS",
    label: "상대 손실",
    description: "ExitMonitor → Publisher → Telegram",
    support: "live",
  },
  {
    id: "KILL_SWITCH",
    label: "Kill Switch",
    description: "일손실·Telegram /kill · ExitMonitor",
    support: "live",
    related: ["POST /risk/kill-switch", "Telegram /kill"],
  },
  {
    id: "DAILY_LOSS",
    label: "일손실",
    description: "DailyLoss / ExitMonitor",
    support: "live",
  },
  {
    id: "AI_ANALYSIS_COMPLETE",
    label: "AI 분석 완료",
    description: "Publisher 이벤트 정의됨 · 호출부 연결은 선택",
    support: "partial",
  },
  {
    id: "BACKTEST_COMPLETE",
    label: "백테스트 완료",
    description: "Publisher 이벤트 정의됨",
    support: "partial",
  },
  {
    id: "BROKER_DISCONNECTED",
    label: "Broker 끊김",
    description: "Publisher 이벤트 정의됨",
    support: "partial",
  },
  {
    id: "BROKER_RECONNECTED",
    label: "Broker 재연결",
    description: "Publisher 이벤트 정의됨",
    support: "partial",
  },
  {
    id: "DATABASE_ERROR",
    label: "DB 오류",
    description: "Publisher 이벤트 정의됨",
    support: "partial",
  },
  {
    id: "SCHEDULER_ERROR",
    label: "Scheduler 오류",
    description: "Publisher 이벤트 정의됨",
    support: "partial",
  },
];

export type TelegramCommandSupport = "live" | "planned";

export interface TelegramOpsCommandSpec {
  command: string;
  label: string;
  description: string;
  support: TelegramCommandSupport;
  restHints: string[];
}

/** STEP54 Telegram Bot 명령 */
export const TELEGRAM_OPS_COMMAND_CATALOG: TelegramOpsCommandSpec[] = [
  {
    command: "/status",
    label: "시스템 상태",
    description: "Server·DB·Broker·Kill Switch·PnL 등",
    support: "live",
    restHints: [
      "GET /api/v1/telegram/ops/status",
      "POST /api/v1/telegram/commands/test",
    ],
  },
  {
    command: "/system",
    label: "시스템 정보",
    description: "프로세스·환경·Telegram 설정",
    support: "live",
    restHints: ["POST /api/v1/telegram/commands/test"],
  },
  {
    command: "/health",
    label: "헬스",
    description: "CPU·Memory·Disk·DB·Broker·Ollama",
    support: "live",
    restHints: ["GET /health", "POST /api/v1/telegram/commands/test"],
  },
  {
    command: "/orders",
    label: "주문 요약",
    description: "오늘 체결·미체결·취소",
    support: "live",
    restHints: ["POST /api/v1/telegram/commands/test"],
  },
  {
    command: "/positions",
    label: "포지션",
    description: "보유·평가손익·수익률",
    support: "live",
    restHints: ["POST /api/v1/telegram/commands/test"],
  },
  {
    command: "/kill",
    label: "Kill Switch ON",
    description: "허용 Chat ID만 실행",
    support: "live",
    restHints: ["POST /api/v1/risk/kill-switch/activate"],
  },
  {
    command: "/resume",
    label: "Kill Switch OFF",
    description: "허용 Chat ID만 실행",
    support: "live",
    restHints: ["POST /api/v1/risk/kill-switch/deactivate"],
  },
  {
    command: "/help",
    label: "도움말",
    description: "명령 목록",
    support: "live",
    restHints: ["POST /api/v1/telegram/commands/test"],
  },
];
