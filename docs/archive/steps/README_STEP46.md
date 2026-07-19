# README_STEP46 — Strategy

## 1. 목표

User Web **Strategy(전략)** 화면을 구현·정리하고 기존 Backend API에 연결한다.

목록·생성·수정·실행·중지·백테스트·Walk Forward 결과를 제공한다.  
삭제·포트폴리오 **최적화** API가 없으면 TODO로 남긴다.

STEP46은 **신규 Backend API를 만들지 않는다.**

---

## 2. 구현 범위

| 기능 | 상태 | 데이터 소스 |
|------|------|-------------|
| 전략 목록 | ✅ 연결 | strategy-operations · active · ranking |
| 전략 생성 | ✅ 연결 | performance runs → complete → deployments |
| 전략 수정 | ✅ 연결 | `POST /strategy-deployments/{id}/update` |
| 전략 삭제 | ⏳ TODO | DELETE API 없음 |
| 전략 실행 | ✅ 연결 | runtime reload + realtime-strategy start |
| 전략 중지 | ✅ 연결 | deployment stop · realtime stop |
| 백테스트 | ✅ 연결 | `POST /backtests/moving-average` · `GET /backtest-runs` |
| Walk Forward 결과 | ✅ 연결 | `POST /walk-forward` |
| 포트폴리오 최적화 | ⏳ TODO | 최적화 API 없음 |
| 가중치 포트폴리오 BT | ✅ 참고 연결 | `POST /portfolio-backtests` |

---

## 3. 주요 파일

```text
README_STEP46.md
frontend/src/app/(user)/user/strategies/page.tsx
frontend/src/features/user/api/userApi.ts
frontend/src/features/user/strategy/normalizeWeights.ts
frontend/src/lib/query/queryKeys.ts
docs/reference/ROADMAPS_README.md
```

---

## 4. TODO (후속)

- [ ] `DELETE /api/v1/strategy-deployments/{id}`
- [ ] 포트폴리오 최적화(최적 가중치) API
- [ ] Walk Forward 영속 조회 UI (`/walk-forward-performance/runs/{id}/windows`)
- [ ] performance complete 더미 메트릭 제거(실 백테스트 결과 연동)

---

## 5. 검증 결과 (2026-07-19)

```powershell
cd D:\Projects\stock-platform\frontend
npm run lint   # 통과 (warning 2건)
npm run test   # 12 files / 27 tests 통과
npm run build  # 통과 (/user/strategies 포함)
```

---

## 6. 완료 체크리스트

- [x] README 초안
- [x] 목록·생성·수정·실행·중지·백테스트·Walk Forward
- [x] 삭제 · 최적화 TODO
- [x] lint / test / build
- [x] README 최종 업데이트

---

## 7. 구현 결과

- `/user/strategies`를 `UserPageShell`로 통일
- 백테스트·Walk Forward·가중치 포트폴리오 BT 폼/결과 표시 추가
- 전략 삭제·포트폴리오 최적화는 `UnimplementedNotice`
- **신규 Backend API 없음**
