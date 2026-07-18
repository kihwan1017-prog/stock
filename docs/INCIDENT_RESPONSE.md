# 장애 대응 가이드 — stock-platform

## 심각도

- **P1**: 주문 오발주/실전 전환 오작동, Kill Switch 미동작
- **P2**: 시세/수집 중단, Outbox 적체, AI 분석 연속 실패
- **P3**: 알림 미발송, 대시보드 지연, Job 단건 실패

## 공통 초기 대응

1. `GET /health`로 장애 컴포넌트 식별
2. Kill Switch 활성화로 신규 매수 차단
   - `POST /api/v1/risk/kill-switch/activate`
3. 실전 주문 플래그 확인 (`KIWOOM_LIVE_ORDER_ENABLED=false` 유지)
4. Outbox / Job 실패 로그 확인
5. 조치 후 `GET /api/v1/audit/events`에 조치 이력이 남았는지 확인

## 시나리오별

### Broker 연결 실패
- Kiwoom credentials / mock 모드 확인
- REST timeout·rate limit 확인
- 계정 sync 재시도 후 미체결 복구

### 데이터 수집 실패
- Upbit/DART/News health 확인
- 해당 Job `scheduler-admin/run-now`로 재실행
- `news/failures`, Job history 확인

### 주문 거부/타임아웃
- `OrderTimeoutService` / Outbox FAILED 확인
- 주문 상태 이력 조회
- REST pending recovery 실행

### 일손실 / Kill Switch 발동
- 원인 손익 확인
- 전략 중지 여부 확인
- 해제는 관리자 키 + 명시적 사유로만 수행

## 사후 조치
- 일일 리포트에 장애 요약 반영
- 재발 방지 항목을 Runbook에 추가
