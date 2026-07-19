# 자주 묻는 질문 (FAQ)

짧은 답만 모았습니다.  
더 긴 절차는 각 매뉴얼을 보세요.

---

## 일반 사용자

### Q. 로그인이 안 돼요. 아이디·비밀번호가 뭔가요?

A. **없습니다.**  
지금 버전은 「**개발 모드로 입장**」 버튼으로 들어갑니다.  
→ [사용자매뉴얼.md](사용자매뉴얼.md)

**[스크린샷]** 「개발 모드로 입장」 버튼

### Q. Trading / Orders 메뉴를 누르면 Coming Soon만 나와요.

A. 맞습니다. 지금은 **대시보드만** 연결되어 있습니다.  
주문·시세·AI는 http://127.0.0.1:8000/docs 에서 처리합니다.  
→ [API사용매뉴얼.md](API사용매뉴얼.md)

### Q. 자동매매를 화면에서 켜고 끄고 싶어요.

A. 그 버튼은 **아직 없습니다.**  
서버 API와 설정으로 제어합니다. → [운영매뉴얼.md](운영매뉴얼.md)

### Q. 왜 실전 주문이 안 나가요?

A. 기본값이 **꺼짐**입니다. (`KIWOOM_LIVE_ORDER_ENABLED=false`)  
실수로 돈이 나가지 않게 막아 둔 것입니다.

### Q. 뉴스는 어디서 보나요?

A. 관리 화면 News는 준비 중입니다.  
API: `/api/v1/news/...` (`/docs` 참고)

### Q. 화면과 문서 내용이 달라요. 뭘 믿어요?

A. **실제로 돌아가는 프로그램(코드·`/docs`)** 이 기준입니다.  
매뉴얼은 “있는 기능만” 적습니다.

---

## 관리자·운영

### Q. Docker Compose로 한 번에 켜나요?

A. **아니요.** Docker를 쓰지 않습니다.  
PostgreSQL은 Windows 서비스로 둡니다. → [설치매뉴얼.md](설치매뉴얼.md)

### Q. Redis는 설치해야 하나요?

A. **아니요. 사용하지 않습니다.**

### Q. Alembic(테이블 만들기)이 실패해요.

A. `alembic current` / `heads` 와 `.\scripts\verify_alembic.ps1` 를 확인하세요.  
“머리가 둘”이면 먼저 정리합니다.  
`docs/migration-overlays` 는 실행하지 마세요.  
→ [DB관리매뉴얼.md](DB관리매뉴얼.md)

### Q. 관리 API가 401이라고 나와요.

A. 설정의 `ADMIN_API_KEY` 와 요청 헤더 `X-Admin-API-Key` 를 맞추세요.  
키가 비어 있으면 **이 PC 개발용**으로는 통과합니다.

### Q. 스케줄러가 안 돌아요.

A. `SCHEDULER_ENABLED=true` 인지,  
`scripts/run_scheduler.py` (또는 Windows 작업)가 켜져 있는지 확인하세요.  
→ [운영매뉴얼.md](운영매뉴얼.md)

### Q. Ollama가 DOWN이에요.

A. Ollama 프로그램을 실행한 뒤 `OLLAMA_BASE_URL` 을 확인하세요.  
AI API는 Ollama가 켜져 있어야 합니다.

### Q. 백업 버튼은 어디에 있나요?

A. 전용 버튼은 없습니다.  
`pg_dump` / `pg_restore` 를 사용합니다. → [백업복구매뉴얼.md](백업복구매뉴얼.md)

### Q. 고장이 났는데 어디서부터 보나요?

A. [장애대응매뉴얼.md](장애대응매뉴얼.md) 의 “먼저 확인할 5가지”부터 보세요.

---

매뉴얼 시작 페이지: [README.md](README.md)
