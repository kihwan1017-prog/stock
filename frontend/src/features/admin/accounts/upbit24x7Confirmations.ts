/**
 * Backend upbit_24x7_control confirmation SoT.
 * UI는 운영자가 타이핑하지 않고 Modal 확인 후 이 문구를 API에 전송한다.
 * Backend safety gate 자체는 완화하지 않는다.
 */

export const CONFIRM_START_RUNTIME = "START RUNTIME";
export const CONFIRM_STOP_RUNTIME = "STOP RUNTIME";
export const CONFIRM_START_WORKER = "START OUTBOX WORKER";
export const CONFIRM_STOP_WORKER = "STOP OUTBOX WORKER";
export const CONFIRM_START_EXIT_MONITOR = "START EXIT MONITOR";
export const CONFIRM_STOP_EXIT_MONITOR = "STOP EXIT MONITOR";

/** 강한 승인(텍스트 입력 유지) — 참고용 상수 */
export const CONFIRM_ENABLE_24H_UNATTENDED = "ENABLE 24H UNATTENDED";
export const CONFIRM_DISABLE_24H_UNATTENDED = "DISABLE 24H UNATTENDED";
export const APPROVAL_ENABLE_UPBIT_LIVE = "ENABLE UPBIT LIVE TRADING";
