# RELEASE_RISK.md — STEP63

**판정:** 고객 Live / 공개망 배포 = **BLOCK**  
**작성:** 2026-07-20

---

## Risk Matrix

| ID | 위험 | 가능성 | 영향 | 등급 | 근거 |
|----|------|--------|------|------|------|
| R-01 | 무인증으로 전략 런타임 전환 | 높음 | 치명 | Critical | `strategy_runtime_switch.switch_strategy_runtime` |
| R-02 | 무인증 일일 파이프라인 실행 | 높음 | 높음 | Critical | `pipelines.execute_daily_strategy_pipeline` |
| R-03 | 무인증 AI/백테스트 DoS | 높음 | 높음 | Critical | `ai_analysis`, `backtest_runs` |
| R-04 | 무인증 브로커/시세 sync | 높음 | 높음 | Critical | `sync.py`, `upbit.py`, `kiwoom_account_sync` |
| R-05 | Outbox Paper 고정 → Live 미전송 | 중 | 치명 | Critical | `outbox_runtime.build_order_outbox_scheduler` |
| R-06 | Outbox crash 후 이중 주문 | 중 | 치명 | Critical | `outbox_worker` PROCESSING 재처리 레이스 |
| R-07 | Telegram webhook 위조 | 중~높 | 치명 | Critical | secret empty → fail-open |
| R-08 | Exit/Risk skip | 중 | 높음 | High | `exit_monitor_runtime` `skip_risk_checks=True` |
| R-09 | Kill Switch 우회 경로 | 중 | 높음 | High | `broker_orders` / cancel-replace |
| R-10 | account_id=1 오주문 | 높음 | 높음 | High | `realtime/runtime.py`, FE defaults |
| R-11 | localStorage XSS 토큰 탈취 | 중 | 높음 | High | `tokenStorage.ts` |
| R-12 | Rate limit 우회 (XFF/멀티인스턴스) | 중 | 중 | High | `rate_limit.client_ip` |
| R-13 | 스케줄러 중복·경합 | 중 | 중 | Medium | lifecycle 다중 scheduler |
| R-14 | DB orphan order | 낮~중 | 중 | Medium | TradingOrder FK 부재 |
| R-15 | Ollama 폭주 | 중 | 중 | Medium | semaphore 없음 |
| R-16 | Alert storm | 중 | 낮~중 | Medium | in-memory dedup |
| R-17 | 문서 drift로 잘못된 조치 | 중 | 중 | Medium | `PROJECT_FINAL_AUDIT.md` |
| R-18 | DR 실패 (schema-only 습관) | 중 | 높음 | High | 백업 절차 준수 필요 |
| R-19 | npm postcss moderate | 낮 | 낮~중 | Low | FE stringify XSS class |
| R-20 | 단일 Windows 인스턴스 SPOF | 확정 | 중 | High | Docker/HA 없음 (의도) |

---

## Go / No-Go Gates

### No-Go (반드시 차단)

- [ ] 공개망에 API 직접 노출  
- [ ] `KIWOOM_LIVE_ORDER_ENABLED=true` 고객 배포  
- [ ] 무인증 mutate API 미봉쇄 상태  
- [ ] Telegram webhook secret 미설정 + webhook 사용  
- [ ] Outbox를 Live라고 가정한 운영  

### Conditional Go (사설망 Paper만)

- [x] `APP_ENV=production` + JWT/ADMIN/CORS 설정  
- [x] `KIWOOM_LIVE_ORDER_ENABLED=false`  
- [x] VPN / 역프록시 / IP allowlist  
- [ ] 잔여 Critical mutate를 네트워크 ACL로 차단하거나 코드 봉쇄  
- [ ] 일간 DB 백업 검증  
- [ ] Kill Switch 수동 리허설  

---

## Incident Scenarios (예상)

### Scenario A — 외부인이 pipeline 실행

1. `POST /api/v1/pipelines/daily-strategy` 무인증  
2. DB·Ollama·외부 API 부하  
3. **완화:** 라우터 `require_admin` 또는 WAF 차단  

### Scenario B — Live라고 믿은 Outbox

1. 운영자가 Live 전환  
2. Outbox는 계속 PaperAdapter  
3. 내부 “체결” vs 실계좌 불일치  
4. **완화:** Outbox를 factory/live adapter에 연결 + 모니터링 지표  

### Scenario C — Webhook 위조 `/kill`

1. secret 미설정  
2. 허용 chat_id를 알면 명령 시도 (allowlist는 방어)  
3. chat_id 유출 시 Critical  
4. **완화:** prod에서 secret 필수 fail-closed  

### Scenario D — Outbox 이중 전송

1. dispatch 후 crash  
2. PROCESSING 재claim / 수동 reset  
3. 브로커에 동일 주문 2회  
4. **완화:** 브로커 idempotency + stale PROCESSING reclaim 정책  

---

## Residual Acceptance (의도적 제약)

다음을 “버그”가 아니라 **제품 전제**로 명시적으로 수용할 때만 내부 배포 가능:

1. Windows 단일 인스턴스 (Docker 없음)  
2. 단일 운영자 / 내부망  
3. Paper 중심 (Live는 별도 게이트)  
4. Ollama 로컬 GPU 공유  

고객 SaaS 수준의 가용성·격리·감사는 **범위 밖**.

---

## Recommended Release Sequence (수정 후)

1. 모든 mutate API에 Admin/Permission  
2. Outbox Live adapter + idempotency  
3. Telegram webhook fail-closed  
4. account_id 하드코딩 제거  
5. Live paper matrix E2E  
6. 재감사 → **APPROVED WITH MINOR ISSUES** 목표  

현재 시점에서는 **고객 배포를 승인하지 않습니다.**
