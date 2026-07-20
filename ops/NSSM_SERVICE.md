# NSSM Windows Service — Stock Platform API

Docker 없이 FastAPI(uvicorn)를 Windows 서비스로 등록합니다.

## 사전 준비

1. [NSSM](https://nssm.cc/download) 설치 후 `nssm.exe` 를 PATH에 추가  
2. [INSTALL.md](../INSTALL.md) 완료 (venv, secrets, alembic)  
3. **관리자** PowerShell

## 등록

```powershell
cd D:\Projects\stock-platform
.\ops\install_nssm_service.ps1
# 옵션: -ServiceName StockPlatformAPI -HostAddress 127.0.0.1 -Port 8000 -OpsRoot E:\StockTrading
```

스크립트가 설정하는 항목:

| 항목 | 값 |
|------|----|
| 실행 파일 | `.venv\Scripts\python.exe` |
| 인자 | `-m uvicorn stock_platform.api.main:app --host ... --port ... --app-dir src` |
| AppDirectory | 프로젝트 루트 |
| PYTHONPATH | `...\src` |
| Start | 자동 시작 |
| 비정상 종료 | Restart (delay 5s) |
| 로그 | `E:\StockTrading\logs\service_stdout.log` / `service_stderr.log` |
| 로테이션 | 10MB |

## 운영 명령

```powershell
nssm start StockPlatformAPI
nssm stop StockPlatformAPI
nssm restart StockPlatformAPI
nssm status StockPlatformAPI
nssm edit StockPlatformAPI   # GUI
```

## 제거

```powershell
.\ops\uninstall_nssm_service.ps1
```

## bat 기동과의 관계

| 방식 | 용도 |
|------|------|
| `start_server.bat` | 수동·임시 기동, 콘솔 최소화 |
| NSSM | 재부팅 후 자동 시작, 크래시 재시작 |

**동시에 둘 다 켜지 마세요** (포트 충돌).

## Task Scheduler 대안

NSSM 없이 시작할 경우:

1. 작업 스케줄러 → 컴퓨터 시작 시  
2. 동작: `D:\Projects\stock-platform\ops\start_server.bat`  
3. 최고 권한으로 실행 (선택)

크래시 자동 재시작은 NSSM이 더 적합합니다.
