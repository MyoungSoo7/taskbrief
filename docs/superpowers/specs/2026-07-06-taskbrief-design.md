# TaskBrief — AI 브리핑 할일 관리 API 설계 문서

- **날짜**: 2026-07-06
- **상태**: 사용자 승인됨
- **목적**: FastAPI 기반 포트폴리오 프로젝트

## 1. 개요와 목표

FastAPI 기반 할일 관리 REST API. 핵심 차별점은 **AI 일일/주간 브리핑**이다: 사용자의 할일 목록을 LLM에 보내 "오늘의 브리핑"(우선순위 요약, 마감 임박 경고, 추천 시작 순서)을 생성하는 엔드포인트를 제공한다.

포트폴리오 목적이므로 다음 품질 요소에 비중을 둔다:

- 계층 분리 (라우터 → 서비스 → 모델)
- 테스트 커버리지 (LLM은 mock으로 외부 의존 없이 전체 테스트 통과)
- 문서화 (README, 자동 OpenAPI 문서)
- 실행 재현성 (Docker, `.env` 설정)

배포(클라우드 호스팅)는 이번 범위에서 제외한다.

## 2. 기술 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| 프레임워크 | FastAPI + Pydantic v2 | 비동기, 자동 OpenAPI 문서 |
| DB | SQLite (aiosqlite), SQLAlchemy 2.0 async ORM | 로컬 개발 단순화. DB URL 설정만 바꾸면 PostgreSQL(asyncpg) 전환 가능 |
| 마이그레이션 | Alembic | 실무 표준 |
| 인증 | OAuth2 Password Flow + JWT (PyJWT), bcrypt 해싱 | 멀티유저, 사용자별 데이터 격리 |
| LLM | Claude API (공식 anthropic SDK, 비동기 클라이언트) | 구조화 출력. API 키는 `.env`로 관리 |
| 테스트 | pytest + pytest-asyncio + httpx AsyncClient | LLM 호출은 mock 대체 |
| 설정 | pydantic-settings | `.env` 기반 환경별 설정 |
| 실행 환경 | Docker + docker-compose | 한 번에 실행 |

## 3. 프로젝트 구조

```
app/
├── main.py              # 앱 팩토리, 라우터 등록
├── db.py                # async 엔진/세션 관리, 세션 의존성
├── core/
│   ├── config.py        # pydantic-settings 설정 (DB URL, JWT 시크릿, API 키)
│   └── security.py      # 비밀번호 해싱, JWT 발급/검증, 현재 사용자 의존성
├── models/              # SQLAlchemy 모델: User, Task, Briefing(캐시)
├── schemas/             # Pydantic 스키마 — 요청/응답 분리
├── routers/
│   ├── auth.py          # /auth/signup, /auth/login
│   ├── tasks.py         # /tasks CRUD
│   └── briefing.py      # /briefing/daily, /briefing/weekly
└── services/
    ├── task_service.py      # 할일 비즈니스 로직
    ├── briefing_service.py  # 브리핑 오케스트레이션 + 캐싱
    └── ai_service.py        # LLM 호출 격리 (프롬프트 구성, 호출, 파싱)
tests/
alembic/
```

**단위별 책임과 경계:**

- `ai_service`: LLM 호출을 완전히 격리한다. 입력은 할일 목록(도메인 객체), 출력은 검증된 브리핑 구조체. 테스트에서 mock으로 대체하는 유일한 지점이며, LLM 교체 시 이 파일만 수정한다.
- `briefing_service`: 캐시 조회 → 할일 수집 → `ai_service` 호출 → 캐시 저장 흐름을 소유한다.
- `routers`: HTTP 관심사(상태 코드, 인증 의존성)만 다루고 로직은 서비스에 위임한다.
- `core/security.py`: 인증 관련 유틸을 한곳에 모아 라우터가 `get_current_user` 의존성만 쓰도록 한다.

## 4. 데이터 모델

**User**: `id, email(unique), hashed_password, created_at`

**Task**: `id, user_id(FK), title, description(nullable), due_date(nullable), priority(low|mid|high), status(todo|doing|done), created_at, updated_at`

**Briefing** (캐시): `id, user_id(FK), kind(daily|weekly), content(JSON), tasks_fingerprint, created_at`

- `tasks_fingerprint`: 브리핑 생성 시점의 대상 할일 상태 해시. 캐시 유효성 판정에 사용.

## 5. API 엔드포인트

### 인증

- `POST /auth/signup` — 이메일+비밀번호 가입. 중복 이메일이면 409. 비밀번호 최소 8자 (Pydantic 검증).
- `POST /auth/login` — OAuth2 Password Flow, JWT access token 발급 (만료 **60분**, 설정으로 변경 가능). 실패 시 401.

### 할일 CRUD (모두 JWT 필요)

- `POST /tasks` — 생성 (201)
- `GET /tasks` — 목록. 필터: `status`, `due_before`, `due_after`. 페이지네이션: `offset`/`limit`(기본 20, 최대 100)
- `GET /tasks/{id}` / `PATCH /tasks/{id}` / `DELETE /tasks/{id}`
- **데이터 격리**: 타인의 할일 접근 시 403이 아닌 **404** 반환 (존재 여부 노출 방지)

### AI 브리핑 (핵심 기능, JWT 필요)

- `GET /briefing/daily` — 오늘 마감이거나 진행 중(doing)이거나, 미착수(todo)이면서 마감이 **3일 이내**인 할일을 대상으로 브리핑 생성
- `GET /briefing/weekly` — 이번 주(월~일) 범위 할일 대상
- 날짜/주 계산의 시간대 기준은 **`Asia/Seoul` 고정** (설정값 `TIMEZONE`으로 변경 가능)
- `urgent_count`는 LLM 출력이 아닌 **서버에서 계산** (마감 3일 이내 미완료 할일 수) — 결정적이고 테스트 가능
- 응답 스키마:

```json
{
  "summary": "string — 자연어 브리핑",
  "urgent_count": 0,
  "suggestions": ["string — 추천 행동"],
  "generated_at": "datetime",
  "cached": false
}
```

## 6. 브리핑 데이터 흐름

```
GET /briefing/daily
→ JWT에서 사용자 확인
→ 대상 할일 조회
→ 할일 0개면: LLM 호출 없이 고정 응답("오늘은 등록된 할일이 없어요") 반환
→ 할일 fingerprint 계산 → 동일 kind의 캐시와 비교
→ 캐시 유효(같은 날 + 같은 fingerprint — daily/weekly 동일 규칙, weekly도 날이 바뀌면 재생성): 캐시 반환 (cached=true)
→ 캐시 무효: 프롬프트 구성 → Claude API 호출 (구조화 JSON 출력 요구)
→ 응답 JSON 파싱 → Pydantic 검증 → Briefing 테이블에 저장 → 반환
```

## 7. 에러 처리

| 상황 | 동작 |
|---|---|
| LLM 타임아웃 (10초) | 1회 재시도 후 실패 시 503 + `{"detail": "AI 브리핑 생성에 실패했습니다. 잠시 후 다시 시도해주세요."}` |
| LLM 응답 JSON 파싱/검증 실패 | 1회 재시도 후 실패 시 503 (위와 동일) |
| API 키 미설정 | 앱 시작은 허용하되 브리핑 엔드포인트만 503 + 명확한 설정 안내 메시지 |
| 인증 실패 | 401 (WWW-Authenticate 헤더 포함) |
| 타인 리소스 접근 | 404 |
| 검증 실패 | FastAPI 기본 422 |

## 8. 테스트 전략

- **인증 플로우**: 가입 → 로그인 → 토큰으로 접근. 중복 가입 409, 잘못된 토큰/만료 토큰 401
- **데이터 격리**: 사용자 A가 B의 할일 조회/수정/삭제 시 404
- **CRUD**: 생성/조회/수정/삭제, 필터·페이지네이션 경계값
- **브리핑**: `ai_service`를 mock으로 대체 — 정상 응답, 타임아웃, 파싱 실패(503), 할일 0개(고정 응답), 캐시 히트(cached=true, LLM 미호출 검증), 할일 변경 후 캐시 무효화
- 테스트 DB는 in-memory SQLite, 테스트별 격리

## 9. 구현 순서

1. 프로젝트 구조 + 설정(pydantic-settings) + DB 세팅 + Alembic 초기화
2. 인증: User 모델, 가입/로그인, JWT 발급/검증, `get_current_user`
3. Task CRUD + 필터/페이지네이션 + 격리 테스트
4. AI 브리핑: `ai_service` → `briefing_service`(캐싱) → 라우터
5. Docker(compose), README, `.env.example`, 마무리 점검

## 10. 범위 제외 (YAGNI)

- 리프레시 토큰 회전 (1차 완성 후 확장 후보)
- 배포/CI (완성 후 별도 단계)
- 프론트엔드
- 이메일 인증, 비밀번호 재설정
- 브리핑 스트리밍(SSE) — 확장 후보로 README에 기록만
