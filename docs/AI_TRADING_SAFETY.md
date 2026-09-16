# AI_TRADING_SAFETY

**최종 갱신:** 2026-07-31 · Cursor `90-trading-safety.mdc` · [AGENTS.md](../AGENTS.md)

---

## 원칙

1. **LIVE 기본 비활성화** (fail-closed startup)  
2. 실주문·Broker 로그인·잔고 실조회·Runtime으로 실거래 유발은 **명시적 승인 Gate**  
3. 계좌별 주문 한도 · 일일 손실 한도 · **Kill Switch** · **Account Pause** 존중  
4. 중복 주문 방지 · Idempotency (Upbit 등 기존 패턴)  
5. Recovery는 주문 생성을 기본으로 하지 않음  
6. Reconciliation로 장부 불일치 해소 — Kiwoom은 P0-2로 미완  
7. Broker 오류는 fail-closed / 재시도 정책 준수  
8. **Paper / LIVE 분리** (계좌·설정·데이터)  
9. **실계좌를 일반 테스트에 사용 금지**

## 현재 판정

- LIVE: **NOT APPROVED**  
- Paper 무인: **NOT READY**  
- P0-1…P0-5 해소 전 LIVE 승인 주장 금지 → [ROADMAP.md](ROADMAP.md)

## 에이전트 금지 (승인 없이)

Broker API · 주문 CRUD · Scheduler/Runtime 무단 기동 · LIVE 플래그 ON · 민감정보 출력
