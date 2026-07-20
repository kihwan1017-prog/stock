# BACKUP.md — stock-platform v1.0.0

관련: [RECOVERY.md](RECOVERY.md) · [docs/manual/백업복구매뉴얼.md](docs/manual/백업복구매뉴얼.md) · `ops/backup_db.bat`

---

## 1. 백업 대상

| 대상 | 경로/방법 | 주기 |
|------|-----------|------|
| PostgreSQL (full) | `pg_dump` → `E:\StockTrading\backups\` | 일 1회 이상 |
| Secrets | `E:\StockTrading\secrets\` 스냅샷 | 변경 시 + 배포 전 |
| 앱 로그 | `E:\StockTrading\logs\` | 필요 시 보관 |
| Git 태그 | 배포 커밋 SHA 기록 | 릴리즈 시 |

**schema-only 덤프만으로 DR하지 마십시오.** 데이터 포함 full dump가 기본입니다.

---

## 2. 표준 백업 (Windows)

```bat
ops\backup_db.bat
```

또는:

```powershell
ops\backup_db.ps1
```

산출물 예:

```text
E:\StockTrading\backups\stock_platform_YYYYMMDD_HHMMSS.dump
```

---

## 3. 배포 전 백업

`ops\update_project.bat` 가 업데이트 직전 백업을 수행합니다.  
수동 업데이트 시에도 **Backup → Stop → Update → Migration → Start → Health** 순서를 지키세요.

---

## 4. 검증

1. 덤프 파일 크기 > 0  
2. 주 1회: 스테이징/별도 인스턴스에서 restore 스모크  
3. secrets 스냅샷과 덤프 시각을 운영 일지에 기록  

---

## 5. 보관

- 최소 7일 로컬 보관 권장  
- 중요 시점(Live 전환 직전, 메이저 마이그레이션)은 별도 오프사이트 복사  

암호화·ACL: `E:\StockTrading\` 디렉터리 NTFS 권한을 운영자만으로 제한합니다.
