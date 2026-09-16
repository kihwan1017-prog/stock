# KI-SEC Known Issues

| ID | 제목 | 코드 상태 | 공개망 | VPN | Paper | LIVE | Blocker? |
|----|------|-----------|--------|-----|-------|------|----------|
| KI-SEC-10 | pipeline mutate 무인증 | **MITIGATED** (`require_admin`) | 낮음 | 낮음 | 낮음 | 낮음 | No |
| KI-SEC-11 | sync/upbit/indicators 무인증 | **MITIGATED** | 낮음 | 낮음 | 낮음 | 낮음 | No |
| KI-SEC-12 | ai/backtest 무인증 | **MITIGATED** | 낮음 | 낮음 | 낮음 | 낮음 | No |
| KI-SEC-13 | runtime_switch/quotes 무인증 | **MITIGATED** | 낮음 | 낮음 | 낮음 | 낮음 | No |
| KI-SEC-14 | step32 deprecated | **MITIGATED** (unmounted) | 없음 | 없음 | 없음 | 없음 | No |
| KI-SEC-15 | Telegram webhook secret 빈 값 | **FIXED** Fail Closed (8-5-21) | 운영 secret 설정 전 webhook 거부 | 동일 | N/A | N/A | 운영 secret 미설정 시 High |

완화: VPN/Internal Only 유지. 공개망 Release Blocker는 네트워크 전제.
