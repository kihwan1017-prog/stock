# APPLY_NOTES

## 적용 순서

1. 현재 작업 커밋
2. ZIP 해제 후 프로젝트 루트에 병합
3. requirements 설치
4. `.env` 설정 반영
5. Alembic `down_revision` 수정
6. migration 실행
7. FastAPI router 등록
8. pytest 실행

## Git 예시

```powershell
cd D:\Projects\stock-platform
git add .
git commit -m "feat(step33): add market data engine foundation"
```

## 기존 Kiwoom 인증 모듈과 연결

`KiwoomMarketClient` 생성 시 토큰 공급 함수를 전달합니다.

```python
client = KiwoomMarketClient(
    base_url=settings.kiwoom_rest_base_url,
    token_provider=existing_token_service.get_access_token,
)
```
