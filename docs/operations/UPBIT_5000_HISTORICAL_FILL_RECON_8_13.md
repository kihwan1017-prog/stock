# STEP 8-13 — Historical Fill Reconciliation (DONE 20건)

조회·분석 전용. Import / Ignore / Pause Resume / LIVE / ARM / 실주문 금지.

## 결과

| 분류 | 건수 |
|------|------|
| ALREADY_FULLY_RECONCILED | 0 |
| MISSING_ORDER_ONLY | 0 |
| MISSING_EXECUTION | 0 |
| **POSITION_RECONCILABLE** | **20** |
| IMPORT_REQUIRED | 0 |
| UNSAFE | 0 |

권고: 전건 `SAFE_IGNORE` (현재 Position/Balance는 Broker 스냅샷과 일치, 내부 주문·체결 이력만 부재).

영향: average_price / realized_pnl / report / tax = 가능(이력 부재). position / balance / risk / future_sell_qty / daily_loss = 현재 상태 기준 없음.

## Pause

Account Pause **해제 불가** (DONE 20건 여전히 PENDING_REVIEW). Ignore는 별도 운영자 승인 STEP 필요.

## 산출물

- 스크립트: `scripts/step8_13_done_fill_reconciliation.py`
- 분류기: `src/stock_platform/trading/step8_13_done_fill_classifier.py`
- JSON: `E:\StockTrading\reports\step8_13_done_fill_reconciliation.json`
