# Kiki Trade AI

> AI 기반 주식 및 가상자산 투자 플랫폼  
> **Current release: v1.0.0**

---

# 프로젝트 소개 (Overview)

Kiki Trade AI는 국내 주식(키움증권 REST API)과 가상자산(Upbit API)을 하나의 플랫폼에서 분석하고 자동매매할 수 있는 AI 투자 플랫폼입니다.

이 프로젝트는 단순한 자동매매 프로그램이 아니라 AI 기반 투자 운영체제(AI Investment Platform)를 목표로 합니다.

## v1.0 빠른 시작

1. [설치](docs/INSTALL.md)
2. [설정](docs/CONFIGURATION.md)
3. [운영 Runbook](docs/OPERATIONS_RUNBOOK.md)
4. [실전 전환 체크리스트](docs/LIVE_TRADING_CHECKLIST.md)
5. 릴리스 검증: `.\scripts\verify_release.ps1`

실전 주문은 기본 차단입니다 (`KIWOOM_LIVE_ORDER_ENABLED=false`).

---

# 프로젝트 목표

- AI 기반 뉴스 분석
- AI 기반 공시 분석
- AI Memory 구축
- 전략 기반 자동매매
- 위험관리(Risk Engine)
- 백테스트
- 투자 Dashboard
- 투자 일지 자동 생성

---

# 시스템 아키텍처

```

Dashboard
│
AI Assistant (OpenClaw)
│
Ollama (Qwen)
│
AI Service (Python)
│
├─────────────┬───────────────┬──────────────┐
│ │ │
News DART Broker
│ │ │
└─────────────┴───────────────┘
│
PostgreSQL + pgvector
│
Strategy Engine
│
Risk Engine
│
Kiwoom REST / Upbit

```

---

# 기술 스택

| 분야 | 기술 |
|------|------|
| Language | Python 3.12 |
| Database | PostgreSQL 17 |
| Vector DB | pgvector |
| AI Runtime | Ollama |
| Local Model | Qwen3.5:4B |
| AI Agent | OpenClaw |
| IDE | Cursor |
| Version Control | Git |
| Stock API | Kiwoom REST |
| Crypto API | Upbit |

---

# 프로젝트 구조

```

stock-platform

├── src/
├── tests/
├── scripts/
├── docs/
├── config/
├── resources/
├── logs/
├── notebooks/
│
├── README.md
├── AGENTS.md
├── SOUL.md
├── requirements.txt
└── .env.example

```

---

# 개발 원칙

## 1. 문서 우선

문서 → 설계 → 개발 → 테스트 → Commit

---

## 2. AI는 주문하지 않는다.

AI는

- 분석
- 요약
- 전략 제안

까지만 수행한다.

실제 주문은

Risk Engine이 승인한 경우에만 Broker가 수행한다.

---

## 3. PostgreSQL 중심

모든 데이터는 PostgreSQL에 저장한다.

- 뉴스
- 공시
- 거래내역
- 전략
- 로그
- AI Memory

---

## 4. Git Commit

기능 하나 완료 → Commit 하나

---

## 5. 테스트

모든 기능은 테스트 후 Commit 한다.

---

# 프로젝트 로드맵

## Phase 1

- 개발환경 구축

완료

---

## Phase 2

- AI 플랫폼 구축

완료

---

## Phase 3

- 프로젝트 표준화

진행중

---

## Phase 4

- PostgreSQL + pgvector

예정

---

## Phase 5

- 뉴스 수집기

예정

---

## Phase 6

- DART 공시

예정

---

## Phase 7

- Kiwoom REST

예정

---

## Phase 8

- Upbit

예정

---

## Phase 9

- Strategy Engine

예정

---

## Phase 10

- Backtesting

예정

---

## Phase 11

- Dashboard

예정

---

# 개발 환경

Windows 11

Python 3.12

PostgreSQL 17

Ollama 0.31.x

OpenClaw 2026.6.x

Cursor

Git

---

# 라이선스

Private Project

Copyright © 2026 Kiki Trade AI
