# 키움·업비트 통합 Live GO/NO-GO 체크리스트

키움 주식 + 업비트 암호자산 통합 자동매매의 **실거래 전환** 전에 확인한다.  
관련 분석: [README_KIWOOM_UPBIT_INTEGRATION_ANALYSIS.md](../architecture/README_KIWOOM_UPBIT_INTEGRATION_ANALYSIS.md)

## 이중 게이트 (필수)

| 게이트 | env | 기본 |
|--------|-----|------|
| 전역 | `GLOBAL_LIVE_ORDER_ENABLED` | `false` |
| 키움 | `KIWOOM_LIVE_ORDER_ENABLED` + `KIWOOM_USE_MOCK=false` | live off / mock on |
| 업비트 | `UPBIT_LIVE_ORDER_ENABLED` + `UPBIT_USE_MOCK=false` | live off / mock on |
| 승인 | Live Trading Transition 활성 | — |

**NO-GO:** 위 중 하나라도 미충족 시 LIVE outbox/adapter 금지.

## STEP 완료 확인

- [ ] STEP2 잔고·연결 테스트 (Admin `/admin/upbit`)
- [ ] STEP3 UpbitBrokerAdapter mock 주문 수락
- [ ] STEP4 Outbox `broker_code`/`environment` 라우팅
- [ ] STEP5 `POST .../reconcile-orders` mock skip / live 폴링
- [ ] STEP6 UPBIT는 KRX 장시간 규칙 스킵, 호가 `lot_rounding` 분기
- [ ] STEP7 Kill Switch `EXCHANGES=UPBIT` reason 스코프 (선택)
- [ ] STEP8 Admin 주문 화면 broker/exchange 필터
- [ ] STEP9 FeePolicy (Paper/백테스트 비용)
- [ ] STEP10 본 체크리스트 + 회귀 스위트

## 회귀 게이트

```bash
# 백엔드
.venv/Scripts/python.exe -m pytest tests/test_upbit_account_auth.py tests/test_upbit_order_adapter.py tests/test_outbox_dispatcher.py tests/test_broker_factory.py tests/test_trading_guards.py -q

# DB
alembic upgrade head   # paper_account.broker_code/exchange_code 포함

# 프론트
cd frontend && npm run typecheck
```

## 운영 스모크

1. `UPBIT_USE_MOCK=true` 로 연결 테스트·잔고 동기화·mock 주문
2. 키움 Paper 주문 회귀 (기존 경로)
3. 모니터링 overview `broker.kiwoom` / `broker.upbit` 상태
4. Kill Switch 활성 시 신규 BUY 차단
5. LIVE 전환 전에만 `GLOBAL`+브로커 LIVE+transition 순서로 활성화

## 시크릿

- Access/Secret은 **env만**. DB 평문 금지.
- 로그는 `security_mask` / 마스킹된 status API만 사용.
