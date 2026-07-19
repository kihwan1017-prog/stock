# README_STEP45 — Auto Trading

## 1. 목표

User Web **자동매매(Auto Trading)** 화면을 구현하고 기존 Backend API에 연결한다.

자동매매 ON/OFF, 실행 전략, 세션 스케줄러(예약), Kill Switch·위험관리 상태, 실행 로그를 표시한다.  
없는 기능은 TODO로 남긴다.

STEP45는 **신규 Backend API를 만들지 않는다.**

---

## 2. 구현 범위

| 기능 | 상태 | 데이터 소스 |
|------|------|-------------|
| 자동매매 ON/OFF | ✅ 연결 | `POST /realtime-strategy/{start,stop}` · `POST /realtime-execution/{start,stop}` · status GET |
| 실행 전략 | ✅ 연결 | `GET /strategy-deployments/active` · `GET /strategy-runtime/status` · strategy status |
| 예약 실행 | ✅ 연결 | `GET/POST /realtime-sessions/{status,start-scheduler,stop-scheduler,run-now/{phase}}` |
| Kill Switch 조회 | ✅ 연결 | `GET /risk/kill-switch` |
| Kill Switch 조작 | ⏳ TODO | activate/deactivate는 Admin(`require_admin`) |
| 위험관리 상태 | ✅ 연결 | `GET /realtime-risk/status` |
| 실행 로그 | ✅ 연결 | `GET /realtime-execution/history` |
| 예약 잡 CRUD | ⏳ TODO | 일괄 start/stop · phase run-now만 존재 |

### 기본 컨텍스트

- Paper 중심 (`mode=PAPER`, `market=KRX`)
- 공용 realtime 러너 사용 (회원 스코프 없음)

---

## 3. 규칙

1. 기존 Backend API만 사용한다.
2. 없는 기능은 `UnimplementedNotice` + TODO로 남긴다.
3. FastAPI에 임의 엔드포인트를 추가하지 않는다.
4. UI는 `UserPageShell` 패턴 (STEP42~44와 동일).

---

## 4. 주요 파일

```text
README_STEP45.md
frontend/src/app/(user)/user/auto-trading/page.tsx
frontend/src/config/routes.ts                 # userRoutes.autoTrading
frontend/src/config/menu.tsx                  # 자동매매 메뉴
frontend/src/features/user/api/userApi.ts
frontend/src/features/user/auto-trading/runnerStatus.ts
frontend/src/lib/query/queryKeys.ts
docs/reference/ROADMAPS_README.md
```

---

## 5. TODO (후속)

- [ ] User Kill Switch activate/deactivate
- [ ] 사용자별 자동매매 설정 CRUD
- [ ] 예약 잡 개별 CRUD
- [ ] 회원 스코프 realtime 러너

---

## 6. 검증 결과 (2026-07-19)

```powershell
cd D:\Projects\stock-platform\frontend
npm run lint   # 통과 (warning 2건)
npm run test   # 11 files / 25 tests 통과
npm run build  # 통과 (/user/auto-trading 포함)
```

---

## 7. 완료 체크리스트

- [x] README 초안
- [x] 자동매매 ON/OFF · 실행 전략 · 예약 · Kill Switch 조회 · 위험관리 · 실행 로그
- [x] User Kill Switch 조작 · 예약 CRUD TODO
- [x] lint / test / build
- [x] README 최종 업데이트

---

## 8. 구현 결과

- 신규 경로 `/user/auto-trading` + 메뉴 **자동매매**
- ON/OFF Switch → strategy + execution 러너 동시 start/stop
- 실행 전략: active deployment 테이블 + runtime Descriptions
- 예약: 세션 스케줄러 start/stop + PRE_MARKET 등 phase run-now
- Kill Switch / realtime-risk 상태 조회
- 실행 로그: realtime-execution/history
- **신규 Backend API 없음**
