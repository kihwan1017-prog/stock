# AI_CODING_RULE

**최종 갱신:** 2026-07-31 · 요약은 [AGENTS.md](../AGENTS.md) · Cursor `10/20-*.mdc`

---

## 공통

- 기존 Service/도메인 재사용. 동일 기능 이중 구현 금지.
- Scope 유지: `user_id`, UBA, Paper account, strategy ownership, scoped runtime.
- 상태 전이는 명시적·감사 가능. 암묵적 전역 상태 금지.
- **Fail-closed** (특히 LIVE·권한·리스크).
- 오류: 도메인 예외 → API 매핑. 삼키지 않음.
- 민감 주문·LIVE·승인: Audit 기록.
- 타입·DTO 안정성. `Any` 남발·스키마 우회 금지.

## Backend

Router ≠ Service. Session 소유권 명확. Broker는 Adapter만. Outbox 우회 실주문 금지.

## Frontend

ADMIN/USER 분리. 미구현 API 가장 금지. Stub 표시. 기존 패턴 유지.

## 자동매매

Realtime에 broker 하드코딩 금지(P0-1). STEP12 승인 파이프라인에서 주문/Runtime WRITE 금지 유지(설계).
