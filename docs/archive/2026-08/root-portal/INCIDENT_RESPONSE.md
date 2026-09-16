# INCIDENT_RESPONSE.md — stock-platform v1.0.0

장애 등급·초동 대응. 관련: [RUNBOOK.md](RUNBOOK.md) · [RECOVERY.md](RECOVERY.md) · [SECURITY.md](SECURITY.md)

---

## 0. 공통 초동 (모든 Critical)

1. **Kill Switch ON**  
2. 신규 배포/마이그레이션 중단  
3. 타임라인·request_id·로그 보존  
4. 영향: 주문·잔고·고객(내부 운영자) 범위 파악  
5. 복구 후 Paper 스모크 → Kill Switch OFF  

---

## 1. Broker Down

**증상:** 주문 거부·타임아웃·WS 단절 · health broker 적색  

**조치:**

1. Kill Switch ON  
2. Outbox PENDING/PROCESSING 건수 확인 — **수동 재전송 금지(이중주문)**  
3. Kiwoom/Upbit 상태·키·mock 플래그 확인  
4. API 재시작으로 세션 재획득  
5. Paper로 경로 확인 후 Live만 재개  

**위험:** Outbox PROCESSING crash 후 재claim → 이중 주문 (Known Issue)

---

## 2. DB Down

**증상:** `/health/ready` 실패 · 5xx · 연결 오류  

**조치:**

1. API 중지 (쓰기 폭주 방지)  
2. PostgreSQL Windows 서비스 상태·디스크·연결 수  
3. 복구 불가 시 [RECOVERY.md](RECOVERY.md) restore  
4. `alembic current` · ready 확인  

---

## 3. AI Timeout

**증상:** Ollama 지연 · AI API 504/timeout · GPU 100%  

**조치:**

1. 거래(주문)와 분리 — Kill Switch는 AI만으로 필수는 아님  
2. Ollama 재시작 · 모델 언로드  
3. 동시 AI 요청 중단 (무인증 AI API 노출 시 네트워크 차단)  
4. `OLLAMA_*` timeout 설정 확인  

---

## 4. Order Failure

**증상:** 거부·미체결·상태 불일치 · 사용자 클레임  

**조치:**

1. Kill Switch ON  
2. TradingOrder / Outbox / Execution / Broker pending 상태 대조  
3. **동일 client order를 재전송하지 말 것** — idempotency 확인  
4. Paper vs Live 어댑터 혼선 여부 (`outbox_runtime` Paper 고정 Known Issue)  
5. 필요 시 브로커 콘솔과 수동 대사 후 문서화  

---

## 5. Memory Leak / High Memory

**증상:** 프로세스 RSS 지속 상승 · OOM  

**조치:**

1. Kill Switch ON → API 재시작 (단기 완화)  
2. 최근 배포·스케줄러·AI·WS 구독 수 확인  
3. 덤프/프로파일은 유지보수 창에서  
4. 재발 시 단일 인스턴스 재시작 주기·구독 상한 검토  

---

## 6. High CPU

**증상:** CPU 고착 · API 지연  

**조치:**

1. backtest/AI/sync 무인증 호출 여부 (방화벽)  
2. N+1 대시보드·스크리너 부하  
3. 불필요 job disable · 재시작  
4. DB slow query 점검  

---

## 7. Telegram 장애 / 위조 의심

1. webhook secret·allowlist 확인  
2. 의심 시 봇 토큰 폐기·재발급  
3. Kill Switch · 감사 로그  

---

## 8. 보안 침해 의심

1. Kill Switch · API 중지 · 네트워크 차단  
2. JWT_SECRET / ADMIN_API_KEY / Broker 키 로테이션  
3. Audit·로그 보존 (덮어쓰기 금지)  
4. [SECURITY.md](SECURITY.md) 절차  

---

## 9. 사후 (Postmortem)

- 타임라인 · 근본 원인 · 재발 방지 (코드/문서/모니터링)  
- Known Issues 갱신 · TOP_100 반영  
