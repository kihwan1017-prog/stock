# FAQ

## 사용자

### Q. 로그인이 안 돼요. 아이디/비밀번호가 뭔가요?

A. Admin JWT 로그인은 **구현되어 있지 않습니다.**  
`NEXT_PUBLIC_AUTH_MODE=disabled`이면 **「개발 모드로 입장」**으로 Dashboard에 들어갑니다.

### Q. Trading / Orders 메뉴가 Coming Soon이에요.

A. STEP41 범위에서 Dashboard만 연결되었습니다.  
실제 주문·시세·AI는 Backend OpenAPI(`http://127.0.0.1:8000/docs`)를 사용하세요.

### Q. 자동매매를 UI에서 켜고 끄려면?

A. Admin UI 버튼은 **없습니다.**  
API의 realtime-strategy / realtime-execution / kill-switch 및 환경변수로 제어합니다. → [운영매뉴얼.md](운영매뉴얼.md)

### Q. 실전 주문이 나가지 않아요.

A. 기본값이 차단입니다 (`KIWOOM_LIVE_ORDER_ENABLED=false`).  
의도된 동작입니다. 실전은 체크리스트·승인 API를 따르세요.

### Q. 뉴스는 어디서 보나요?

A. Admin News 페이지는 Coming Soon입니다.  
API: `/api/v1/news/...`

---

## 관리자

### Q. Docker Compose가 있나요?

A. **없습니다.** PostgreSQL은 Windows 서비스로 운영합니다.

### Q. Redis는요?

A. **사용하지 않습니다.**

### Q. Alembic이 실패합니다.

A. `alembic current` / `heads`, `.\scripts\verify_alembic.ps1`  
multiple heads면 chain을 먼저 정리합니다. Overlay 폴더는 실행하지 마세요.

### Q. 관리 API가 401입니다.

A. `ADMIN_API_KEY`와 헤더 `X-Admin-API-Key`를 맞추세요.  
키가 비어 있으면 개발 모드로 통과합니다.

### Q. 스케줄러가 안 돌아요.

A. `SCHEDULER_ENABLED=true`인지, `scripts/run_scheduler.py`(또는 Windows 작업)가 떠 있는지 확인하세요.

### Q. Ollama가 DOWN입니다.

A. Ollama 앱 실행 후 `OLLAMA_BASE_URL`을 확인하세요. AI API는 Ollama에 의존합니다.

### Q. 문서와 UI가 다른데 어느 쪽이 맞나요?

A. **코드·OpenAPI가 기준**입니다. 매뉴얼은 구현된 기능만 기술합니다.  
미구현 UI는 Coming Soon으로 명시했습니다.

### Q. 백업 스크립트는 어디에 있나요?

A. 전용 스크립트는 없습니다. `pg_dump`/`pg_restore`를 사용합니다. → [백업복구매뉴얼.md](백업복구매뉴얼.md)

---

더 많은 운영 Q&A: [장애대응매뉴얼.md](장애대응매뉴얼.md)
