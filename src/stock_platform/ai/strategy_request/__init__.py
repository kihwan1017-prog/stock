"""STEP 12-1 — AI Candidate -> Strategy Request 승인 게이트.

AI가 생성한 Candidate(ai.candidate_lifecycle)를 즉시 Strategy로 승격하지
않고, 반드시 사람(관리자)의 심사를 거쳐 Strategy Request를 생성한다.

Strategy Draft 생성(STEP12-2 이후)은 이 패키지의 범위가 아니다.
AI 호출, Broker/Order/Runtime/Scheduler WRITE는 수행하지 않는다.
"""
