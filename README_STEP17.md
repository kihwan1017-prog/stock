# STEP 17 - Kiwoom REST Client

이 패키지는 키움 REST API의 인증과 공통 요청 기반을 추가합니다.

## 포함 기능

- 접근토큰 발급 및 메모리 캐시
- 운영/모의투자 서버 전환
- `authorization`, `api-id`, `cont-yn`, `next-key` 처리
- 프로세스 단위 초당 호출 제한
- 네트워크 및 서버 오류 재시도
- FastAPI 설정 확인 및 토큰 테스트 API
- 실제 키를 사용하지 않는 단위 테스트

## 공식 API 기준

키움 REST API 접근토큰 발급:

- 운영: `https://api.kiwoom.com`
- 모의: `https://mockapi.kiwoom.com`
- 경로: `/oauth2/token`
- 방식: `POST`
- Body: `grant_type`, `appkey`, `secretkey`

일반 REST 요청은 다음 헤더를 사용합니다.

- `authorization: Bearer <token>`
- `api-id: <TR 코드>`
- 연속 조회 시 `cont-yn`, `next-key`

## 적용 전 주의

먼저 프로젝트 상태를 확인하세요.

```powershell
git status
```

작업 중인 변경사항이 있으면 커밋하거나 백업한 뒤 압축을 풉니다.

## 파일 적용

ZIP을 다음 프로젝트 루트에 압축 해제합니다.

```text
D:\Projects\stock-platform
```

`settings.py`와 `api/router.py`는 기존 파일을 확장한 완성본이므로,
현재 프로젝트 구조가 STEP 16과 동일할 때 덮어쓰세요.

## 키움 비밀키 등록

다음 파일에 실제 값을 추가합니다.

```text
E:\StockTrading\secrets\stock-platform.env
```

예:

```dotenv
KIWOOM_APP_KEY=발급받은_앱키
KIWOOM_SECRET_KEY=발급받은_시크릿키
KIWOOM_USE_MOCK=true
KIWOOM_TIMEOUT_SECONDS=10
KIWOOM_MAX_REQUESTS_PER_SECOND=5
```

실제 키를 프로젝트의 `.env`, README, Git에 넣지 마세요.

## 설정 확인

서버 실행:

```powershell
uvicorn stock_platform.api.main:app --reload --app-dir src
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

설정 확인:

```text
GET /api/v1/kiwoom/configuration
```

실제 토큰 발급 테스트:

```text
POST /api/v1/kiwoom/token/test
```

토큰 값 자체는 API 응답이나 로그에 출력하지 않습니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
python -m pytest tests\test_kiwoom_auth.py tests\test_kiwoom_client.py -q
```

`pytest`가 없다면:

```powershell
python -m pip install pytest
```

## Git 커밋

```powershell
git add `
    README_STEP17.md `
    config\kiwoom.env.example `
    src\stock_platform\common\settings.py `
    src\stock_platform\brokers\kiwoom `
    src\stock_platform\api\v1\kiwoom.py `
    src\stock_platform\api\router.py `
    tests\test_kiwoom_auth.py `
    tests\test_kiwoom_client.py

git commit -m "feat(kiwoom): add REST authentication client"
```

## 안전 범위

이번 단계에는 주문 API가 포함되지 않습니다.

- 인증
- 공통 조회 요청 기반
- 연속 조회 메타데이터

까지만 구현합니다. 실제 주문은 위험관리 계층을 만든 뒤 별도 단계에서 추가합니다.
