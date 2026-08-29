# RECOVERY.md — stock-platform v1.0.0

관련: [BACKUP.md](BACKUP.md) · [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) · `ops/restore_db.bat`

---

## 1. 복구 원칙

1. **Kill Switch 활성화** (주문 유입 차단)  
2. API / Frontend 중지  
3. 손상 여부 확인 (DB 연결, 디스크, 최근 덤프)  
4. Restore  
5. Migration head 확인  
6. Health / Ready  
7. Paper 스모크 후 Kill Switch 해제  

---

## 2. DB 복구

```bat
ops\stop_server.bat
ops\restore_db.bat E:\StockTrading\backups\<dump파일>
ops\start_server.bat
ops\health_check.bat
```

PowerShell:

```powershell
ops\restore_db.ps1 -DumpPath "E:\StockTrading\backups\stock_platform_....dump"
```

주의:

- Restore는 **기존 DB를 덮어쓸 수 있습니다.** 대상 DB를 재확인하세요.  
- Restore 후 `alembic current` / `alembic upgrade head` 로 스키마 정합 확인  
- Canonical 경로: `database/alembic` (root `alembic/` overlay와 혼동 금지)

---

## 3. Secrets 복구

1. `E:\StockTrading\secrets\stock-platform.env` 백업본 복원  
2. `JWT_SECRET` 변경 시 **모든 세션 무효** → 재로그인  
3. Broker 키 로테이션 시 키움/업비트 콘솔과 동기화  

---

## 4. 코드 롤백

```powershell
cd D:\Projects\stock-platform
git fetch
git checkout <known-good-tag-or-sha>
# pip / npm 재설치는 버전 차이에 따라
ops\update_project.bat   # 또는 수동 Stop→Start
```

기존 Git 태그 `v1.0.0`이 오래된 커밋을 가리킬 수 있습니다.  
GA 태그 재생성 절차는 [README_STEP64.md](README_STEP64.md)를 참고하세요.

---

## 5. 복구 후 점검

| 항목 | 확인 |
|------|------|
| `GET /health/live` | 200 |
| `GET /health/ready` | 200 |
| `GET /version` | version=1.0.0 |
| Kill Switch | 의도대로 ON/OFF |
| Outbox / Scheduler | 중복 job 없는지 |
| Paper 주문 1건 | 성공 후 취소/조회 |

실패 시 [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)의 DB Down / Order Failure 절차를 따릅니다.
