# CHANGELOG 가이드

제품·문서의 변경 이력을 읽고 남기는 방법입니다.

## 어디를 보나

| 파일 | 내용 |
|------|------|
| [../../CHANGELOG.md](../../CHANGELOG.md) | 릴리스·문서·기능 변경 요약 |
| Git tag | 예: `v1.0.0` |
| `docs/archive/steps/` | STEP 작업 로그 (과거 개발 기록) |

## 읽는 법

1. 최신 섹션이 위 (`Unreleased` → 버전 태그)
2. `Added` / `Changed` / `Fixed` / `Security` / `Docs` 구분
3. 운영 영향이 큰 항목: Security·실전 주문·마이그레이션

## 작성 규칙 (관리자)

새 릴리스 전에 `CHANGELOG.md`의 `Unreleased`를 버전 섹션으로 옮깁니다.

```markdown
## Unreleased

### Docs
- ...

## x.y.z — YYYY-MM-DD

### Added
- ...
```

- 사용자 영향 중심으로 **왜** 바뀌었는지 한 줄
- 시크릿·개인정보 금지
- 매뉴얼 변경 시 `docs/manual/` 링크를 Docs에 남김

## 매뉴얼과의 관계

기능이 추가되면:

1. 코드·테스트 반영  
2. OpenAPI 확인  
3. 해당 매뉴얼 절 업데이트 (추측 금지)  
4. `CHANGELOG.md` Docs/Added 항목 추가  

목차: [README.md](README.md)
