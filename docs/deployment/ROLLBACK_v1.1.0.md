# ROLLBACK_v1.1.0

배포 실패·심각한 회귀 시. **운영 DB 자동 파괴 명령 금지.**

---

## 원칙

1. 트래픽/서비스 중지
2. 코드 롤백
3. DB는 **백업 restore 우선** (downgrade는 스키마 전용·데이터 손실 위험)
4. Env 복구
5. Health 확인

---

## A. Code Rollback

```bat
ops\stop_server.bat
git checkout v1.0.0
REM 또는 직전 안정 커밋
.\.venv\Scripts\pip.exe install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
ops\start_server.bat
```

`APP_VERSION`이 1.0.0으로 돌아가는지 `GET /version` 확인.

---

## B. Database

### 권장: Backup Restore

1. 배포 직전 dump로 restore ([RECOVERY.md](../../RECOVERY.md) / [BACKUP.md](../../BACKUP.md))
2. `alembic current`가 v1.0.0 시점 revision인지 확인

### 대안: Alembic Downgrade (주의)

STEP65–73이 여러 revision입니다.  
데이터 보존이 필요하면 **downgrade보다 restore**.

```bat
REM 예시 — 대상 revision은 배포 전 current를 기록해 둘 것
.\.venv\Scripts\python.exe -m alembic downgrade <pre_1_1_0_revision>
```

---

## C. Env

배포 전 복사본으로 `stock-platform.env` 복구.  
Secret 재생성 시 JWT/세션 전체 무효화됨을 공지.

---

## D. 검증

- `/health/ready` OK
- 로그인·Paper 조회
- 사용자 신규 테이블 의존 화면은 v1.0.0에서 미지원 → 기대치 안내
