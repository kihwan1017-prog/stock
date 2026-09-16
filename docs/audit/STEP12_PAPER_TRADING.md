# STEP 12 — Paper Trading 검증

## 구조
- Outbox PaperBrokerAdapter: accept-only 스텁
- 원장 PaperOrderEngine+PaperExecutionService: 체결·잔고

## 수정
- fill/cancel/reject 소유권 검증
- apply_fill account_id 일치 검증
- RealtimePaperOrderExecutor에 account_id 전달

## 남은 문제
save() 조기 commit 원자성, fee 미연동, Outbox↔원장 단절(의도적 분리 문서화), replace 미구현

## 권장 커밋
ix(step12): enforce paper order ownership and account match
