# STEP35 테스트 결과 요약

> 실행일: 2026-07-18  
> 명령: `pytest -m "not external and not live"`  
> Docker 미사용

## 결과

| 항목 | 값 |
|------|-----|
| Passed | **216** |
| Skipped | **3** |
| Failed | **0** |
| 소요 | ~2.1s |

## Skip 분류

| 테스트 | 사유 | 후속 |
|--------|------|------|
| `test_kiwoom_rest_adapter.py` | Adapter 생성자 keyword-only로 변경 | STEP36/38 mock 재작성 |
| `test_risk_service.py` (2건) | RiskService persistence API 제거 | STEP38 risk 패키지 통합 |

## 인프라 정리 (TASK 35-07)

- `pytest.ini`: 기본 `-m "not external and not live"`
- `tests/conftest.py`: marker 정의
- 수집 충돌 해소: `tests/step34/test_step34_indicator.py`로 이름 변경

## STEP35 완료 범위

| TASK | 상태 |
|------|------|
| 35-01 Lifespan | 완료 |
| 35-02 Router | 완료 |
| 35-03 Settings | 완료 |
| 35-04 Domain map | 완료 (`docs/development/DOMAIN_PACKAGE_MAP.md`) |
| 35-05 Exceptions | 완료 |
| 35-06 Alembic | 완료 (head `b8f4c2a19e03`) |
| 35-07 Tests | 완료 (본 문서) |

## 재실행

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
pytest -m "not external and not live"
```
