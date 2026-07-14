# STEP23-3 AI Top5 포지션 계획 일괄 생성

최신 AI 후보평가 결과와 저장된 위험관리 정책을 연결해
최대 Top5의 주문 전 포지션 계획을 일괄 생성합니다.

## 처리 흐름

```text
ai.candidate_analysis_run
        ↓
ai.candidate_analysis_result
        ↓
AI 점수·신뢰도·Action 필터
        ↓
최신 일봉 종가 조회
        ↓
strategy.risk_policy 적용
        ↓
strategy.position_plan 저장
```

## 중요

실제 주문은 전송하지 않습니다.

이번 단계는 다음만 수행합니다.

- AI 후보 필터링
- 현재 종가 조회
- 가용 현금 순차 차감
- 최대 보유 종목 수 반영
- 손절·익절·수량 계산
- 포지션 계획 DB 저장

## 적용 파일

```text
src/stock_platform/risk/allocation_service.py
src/stock_platform/risk/__init__.py
src/stock_platform/api/v1/position_candidates.py
src/stock_platform/api/router.py
tests/test_candidate_position_plan_service.py
```

신규 테이블이 없으므로 Alembic 작업은 필요 없습니다.

## 사전 조건

- STEP22-2 AI 분석 결과 테이블
- STEP22-5 AI 오케스트레이션 결과
- STEP23-2 위험관리 정책 및 포지션 계획 테이블
- 대상 종목의 `market.price_daily` 최신 데이터

## API

```text
POST /api/v1/position-candidates/plans
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "policy_id": 1,
  "portfolio_value": 10000000,
  "available_cash": 5000000,
  "current_position_count": 0,
  "limit": 5,
  "minimum_ai_score": 70,
  "minimum_confidence": 0.5,
  "allowed_actions": [
    "WATCH",
    "REVIEW"
  ]
}
```

승인된 계획은 `strategy.position_plan`에 저장됩니다.
거절된 계획도 거절 사유와 함께 저장됩니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_candidate_position_plan_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP23_3.md `
    src\stock_platform\risk\allocation_service.py `
    src\stock_platform\risk\__init__.py `
    src\stock_platform\api\v1\position_candidates.py `
    src\stock_platform\api\router.py `
    tests\test_candidate_position_plan_service.py

git commit -m "feat(risk): create AI candidate position plans"
```

다음 단계는 STEP24 모의 주문 및 주문 상태 관리입니다.
