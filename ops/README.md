# ops — Windows 운영 스크립트 (STEP60)

Docker 없이 수동·NSSM 운영을 지원합니다.

| 스크립트 | 설명 |
|----------|------|
| `start_server.bat` | API 시작 |
| `stop_server.bat` | API 중지 |
| `restart_server.bat` | 재시작 |
| `health_check.bat` | Health |
| `backup_db.bat` | DB 백업 |
| `restore_db.bat` | DB 복구 |
| `update_project.bat` | 무중단이 아닌 표준 업데이트 |
| `deploy_check.bat` | 배포 점검 |
| `install_nssm_service.ps1` | Windows Service 등록 |
| `env.production.example` | 운영 env 템플릿 |

문서: [../INSTALL.md](../INSTALL.md) · [../OPERATIONS.md](../OPERATIONS.md) · [NSSM_SERVICE.md](NSSM_SERVICE.md)

환경 변수 `STOCK_OPS_ROOT` 로 데이터 루트 변경 가능 (기본 `E:\StockTrading`).
