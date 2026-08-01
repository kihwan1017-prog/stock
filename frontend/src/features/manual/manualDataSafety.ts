import type { ManualGuideStep } from "./manualTypes";

export const SAFETY_SHUTDOWN_STEPS: ManualGuideStep[] = [
  {
    id: "k1",
    title: "1. Kill Switch ON",
    detail: "시스템 Kill Switch를 켜 신규 주문을 즉시 차단합니다.",
    status: "available",
  },
  {
    id: "k2",
    title: "2. Runtime STOP",
    detail: "관련 Scope Runtime을 STOP합니다. 중복 실행이 있으면 모두 중지합니다.",
  },
  {
    id: "k3",
    title: "3. 신규 주문 0 확인",
    detail: "주문관리·사용자 주문 화면에서 신규 접수가 멈췄는지 확인합니다.",
  },
  {
    id: "k4",
    title: "4. 미체결 주문 확인",
    detail: "미체결(ACK/PARTIAL 등)을 목록화합니다.",
  },
  {
    id: "k5",
    title: "5. 필요 시 거래소 수동 취소",
    detail:
      "플랫폼에서 취소가 불확실하면 거래소/증권사 콘솔에서 수동 취소합니다.",
    status: "conditional",
  },
  {
    id: "k6",
    title: "6. Position과 실제 잔고 비교",
    detail: "원장 Position/Balance와 브로커 잔고를 대조합니다.",
  },
  {
    id: "k7",
    title: "7. Recovery/Reconciliation",
    detail: "장애 복구·Reconciliation을 실행하고 Conflict를 해소합니다.",
  },
  {
    id: "k8",
    title: "8. WebSocket 상태 확인",
    detail: "실시간 연결 장애·재연결 루프를 확인합니다.",
  },
  {
    id: "k9",
    title: "9. 원인 확인 후 재개",
    detail: "원인 제거·Gate 통과 후에만 Runtime을 재개합니다. LIVE는 추가 승인 필요.",
    status: "admin_approval",
  },
];

export const SAFETY_IMMEDIATE_STOP_CONDITIONS: string[] = [
  "중복 주문",
  "중복 체결",
  "예상하지 않은 종목 주문",
  "한도 초과 주문",
  "Position/실제 잔고 불일치",
  "Recovery Conflict",
  "주문 ID 누락",
  "반복적인 WebSocket 장애",
  "Credential 또는 Secret 노출 가능성",
];
