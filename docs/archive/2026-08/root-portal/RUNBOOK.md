# RUNBOOK.md — stock-platform v1.0.0

일상 운영 절차. 관련: [OPERATIONS.md](OPERATIONS.md) · [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) · `ops/`

---

## 1. 서비스 시작

```bat
ops\start_server.bat
ops\health_check.bat
```

NSSM:

```powershell
nssm start StockPlatformAPI
```

Frontend (별도):

```powershell
cd D:\Projects\stock-platform\frontend
npm run start
```

확인: `GET /health/live` · `GET /health/ready` · `GET /version` → `1.0.0`

---

## 2. 서비스 종료

```bat
ops\stop_server.bat
```

```powershell
nssm stop StockPlatformAPI
```

종료 전: 진행 중 주문/Outbox 잔량 확인 권장. 긴급 시 Kill Switch 먼저.

---

## 3. 재시작

```bat
ops\restart_server.bat
```

또는 `nssm restart StockPlatformAPI`  
재시작 후 health + Kill Switch 상태 + 스케줄러 로그 확인.

---

## 4. Broker 재연결

1. `KIWOOM_USE_MOCK` / Live 플래그 확인  
2. API 재시작 또는 Kiwoom WS/세션 Admin API (권한 필요)  
3. `ops\health_check.bat` 및 monitoring overview  
4. Paper 주문 1건으로 경로 검증  
5. Live는 **별도 체크리스트** 후에만

토큰 만료·HTTP 401 시 secrets의 App Key/Secret 재확인.

---

## 5. DB 복구

[RECOVERY.md](RECOVERY.md) · `ops\restore_db.bat <dump>`

---

## 6. Telegram 장애

| 증상 | 조치 |
|------|------|
| 알림 없음 | `TELEGRAM_BOT_TOKEN` · enabled 플래그 · 네트워크 |
| 명령 무시 | `TELEGRAM_ALLOWED_CHAT_IDS` · webhook secret |
| 중복 명령 | poller와 webhook 동시 사용 여부 확인 → 하나만 |
| 위조 우려 | secret 설정 · Kill Switch · 토큰 로테이션 |

상세: [SECURITY.md](SECURITY.md)

---

## 7. Ollama 장애

1. `ollama serve` / 서비스 상태  
2. `OLLAMA_BASE_URL` (기본 `http://127.0.0.1:11434`)  
3. 모델 pull 여부  
4. AI API 타임아웃 — 거래 경로는 AI 없이도 동작해야 함  
5. GPU 메모리 부족 시 동시 요청 줄이기 (Semaphore 없음 — Known Issue)

---

## 8. Scheduler 장애

1. API 프로세스 생존 여부  
2. `job_run_history` / Admin Jobs  
3. 중복 실행 의 시 **단일 인스턴스만** 기동했는지 확인  
4. 필요 시 API 재시작  
5. Outbox PENDING 적체 시 worker 로그·DB 상태 확인

---

## 9. Kill Switch

활성화 (긴급):

- Admin API: `POST /api/v1/risk/kill-switch/activate` (+ Admin 인증)  
- 또는 Admin UI / Telegram 허용 명령 (설정 시)

해제:

- `POST .../deactivate` — **원인 제거·점검 후에만**

활성화 중에도 일부 우회 경로가 있을 수 있음 → [KNOWN_ISSUES.md](KNOWN_ISSUES.md)

---

## 10. Daily Loss

1. Daily Loss Monitor 설정·한도 확인  
2. 한도 초과 시 신규 주문 차단되는지 로그/이벤트로 확인  
3. 일중 리셋·캘린더(KST) 확인  
4. 오탐 시 한도/집계 소스(실현손익) 점검 후 조정

---

## 11. 일일 점검 (권장)

- [ ] Health live/ready  
- [ ] 전일 백업 존재  
- [ ] Kill Switch OFF (의도적)  
- [ ] Outbox 적체 없음  
- [ ] 디스크/로그 용량  
- [ ] Broker mock/live 플래그 의도대로  
