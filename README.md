# TaskBrief

**AI 브리핑 기능이 있는 할일 관리 REST API.** 사용자별 할일을 관리하고, 등록된 할일을 LLM에 보내 "오늘 무엇을 먼저 해야 하는지"를 요약해 주는 일일/주간 브리핑을 제공한다. FastAPI 기반 포트폴리오 프로젝트로, 계층 분리·테스트 용이성·실행 재현성에 비중을 두고 설계했다.

## 핵심 기능

- **JWT 멀티유저**: OAuth2 Password Flow + JWT 기반 인증. 사용자별 데이터가 완전히 격리된다.
- **할일 CRUD + 필터/페이지네이션**: 생성·조회·수정·삭제. `status`, `due_before`, `due_after` 필터와 `offset`/`limit` 페이지네이션 지원.
- **AI 일일/주간 브리핑**: 대상 할일을 Claude API에 보내 우선순위 요약·추천 행동을 생성. `urgent_count`(마감 임박 건수)는 LLM이 아닌 서버가 결정적으로 계산한다.
- **fingerprint 캐싱**: 같은 날 + 할일 상태가 그대로면 이전 브리핑을 재사용해 불필요한 LLM 호출을 막는다.

## 아키텍처

계층 구조는 **라우터 → 서비스 → 모델**로 단방향 의존한다. 라우터는 HTTP 관심사(상태 코드, 인증 의존성)만 다루고 비즈니스 로직은 서비스에 위임한다.

```
HTTP 요청
  │
  ▼
routers/            HTTP 관심사만 (상태 코드, 인증 의존성)
  ├─ auth.py        /auth/signup, /auth/login, /auth/me
  ├─ tasks.py       /tasks CRUD + 필터/페이지네이션
  └─ briefing.py    /briefing/daily, /briefing/weekly
  │
  ▼
services/           비즈니스 로직
  ├─ task_service.py       할일 CRUD 로직
  ├─ briefing_service.py   브리핑 오케스트레이션 + 캐싱
  └─ ai_service.py         LLM 호출 격리 (프롬프트 구성 · 호출 · 파싱 · 검증)
  │
  ▼
models/             SQLAlchemy 모델: User, Task, Briefing(캐시)
core/               config.py(설정), security.py(해싱 · JWT · get_current_user)
db.py               async 엔진/세션 관리
```

### `ai_service` 격리 설계

LLM 호출은 `ai_service` 한 파일에 완전히 격리되어 있다. 입력은 도메인 객체(할일 목록)이고 출력은 Pydantic으로 검증된 브리핑 구조체(`AIBriefingResult`)다. 이 경계 덕분에 (1) 테스트에서 `ai_service`만 mock으로 대체하면 API 키 없이 전체 흐름을 검증할 수 있고, (2) 다른 LLM 제공자로 교체할 때 이 파일만 수정하면 된다. `briefing_service`와 라우터는 LLM의 존재를 알 필요가 없다.

### 브리핑 데이터 흐름

```
요청 (GET /briefing/daily | /briefing/weekly)
  → JWT에서 사용자 확인
  → 대상 할일 조회 (daily: doing이거나 마감 3일 이내 / weekly: doing이거나 이번 주 범위)
  → 할일 0개면: LLM 호출 없이 고정 메시지 반환
  → 대상 할일의 fingerprint 계산 → 같은 kind의 최신 캐시와 비교
  → 캐시 유효(같은 로컬 날짜 + 같은 fingerprint): 캐시 반환 (cached=true)
  → 캐시 무효: 프롬프트 구성 → Claude API 호출 (JSON 출력 요구)
  → 응답 파싱 → Pydantic 검증 → Briefing 테이블에 저장 → 반환 (cached=false)
```

`urgent_count`는 캐시 히트/미스와 무관하게 항상 최신값으로 다시 계산해, 대상 밖 할일이 바뀌어도 정확한 마감 임박 건수를 반영한다.

## 기술 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| 프레임워크 | FastAPI + Pydantic v2 | 비동기, 자동 OpenAPI(Swagger) 문서 |
| DB / ORM | SQLite(aiosqlite) + SQLAlchemy 2.0 async | 로컬 개발 단순화. `DATABASE_URL`만 바꾸면 PostgreSQL(asyncpg) 전환 가능 |
| 마이그레이션 | Alembic | 스키마 버전 관리 실무 표준 |
| 인증 | OAuth2 Password Flow + JWT(PyJWT), bcrypt 해싱 | 멀티유저, 사용자별 데이터 격리 |
| LLM | Claude API (공식 `anthropic` 비동기 SDK) | 구조화 JSON 출력. API 키는 `.env`로 관리 |
| 설정 | pydantic-settings | `.env` 기반 환경별 설정 |
| 테스트 | pytest + pytest-asyncio + httpx AsyncClient | LLM 호출은 mock으로 대체 |
| 실행 환경 | Docker + docker compose | 한 번에 실행 |

## 빠른 시작

Python 3.12 기준. 아래는 Windows PowerShell 명령이다.

### 로컬 실행

```powershell
# 1. 환경 변수 파일 생성
Copy-Item .env.example .env

# 2. 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. 의존성 설치
.venv\Scripts\python -m pip install -r requirements.txt

# 4. DB 마이그레이션
.venv\Scripts\alembic upgrade head

# 5. 서버 실행
.venv\Scripts\uvicorn app.main:app --reload
```

### Docker 실행

```powershell
Copy-Item .env.example .env
docker compose up --build
```

실행 후 브라우저에서 **http://127.0.0.1:8000/docs** 를 열면 Swagger UI로 모든 엔드포인트를 직접 호출해 볼 수 있다. 수동 테스트용 요청 모음은 [`requests.http`](./requests.http)에 정리되어 있다.

## API 개요

| 메서드 | 경로 | 설명 | 인증 |
|---|---|---|:---:|
| GET | `/health` | 헬스체크 | — |
| POST | `/auth/signup` | 회원가입 (이메일 + 비밀번호, 중복 시 409) | — |
| POST | `/auth/login` | 로그인 (OAuth2 password form → JWT 발급) | — |
| GET | `/auth/me` | 현재 사용자 정보 | 필요 |
| POST | `/tasks` | 할일 생성 (201) | 필요 |
| GET | `/tasks` | 할일 목록 (필터: `status`, `due_before`, `due_after` / 페이지네이션: `offset`, `limit`) | 필요 |
| GET | `/tasks/{id}` | 할일 단건 조회 | 필요 |
| PATCH | `/tasks/{id}` | 할일 수정 | 필요 |
| DELETE | `/tasks/{id}` | 할일 삭제 (204) | 필요 |
| GET | `/briefing/daily` | AI 일일 브리핑 | 필요 |
| GET | `/briefing/weekly` | AI 주간 브리핑 | 필요 |

- 비밀번호는 최소 8자(Pydantic 검증). 로그인 실패 시 401.
- 타인의 할일에 접근하면 403이 아닌 **404**를 반환한다(존재 여부 노출 방지).
- `limit` 기본값 20, 최대 100.

## AI 브리핑 사용법

브리핑 엔드포인트가 **실제 LLM 브리핑**을 생성하려면 서버 `.env`에 `ANTHROPIC_API_KEY`가 설정되어 있어야 한다.

- API 키가 없으면 브리핑 엔드포인트는 **503**과 안내 메시지(`"AI 기능이 설정되지 않았습니다. 서버에 ANTHROPIC_API_KEY를 설정해주세요."`)를 반환한다. 앱 자체는 정상 기동하며 다른 엔드포인트는 영향받지 않는다.
- LLM 호출이 실패하면 1회 재시도 후에도 실패 시 **503**(`"AI 브리핑 생성에 실패했습니다..."`)을 반환한다.
- 대상 할일이 0개면 LLM을 호출하지 않고 고정 메시지를 반환한다.

**`urgent_count`** 는 LLM 출력이 아니라 서버가 계산한다: 마감이 **3일 이내(이미 지난 것 포함)** 인 미완료 할일 수. 결정적이라 테스트로 검증 가능하다.

**캐싱**: `(로컬 날짜(Asia/Seoul) + 대상 할일의 fingerprint)`가 이전 브리핑과 같으면 저장된 결과를 재사용한다(`cached: true`). 할일을 추가·수정·삭제하거나 날짜가 바뀌면 fingerprint/날짜가 달라져 새로 생성된다. daily·weekly에 같은 규칙이 적용된다.

응답 예시:

```json
{
  "summary": "자연어 브리핑 (2~4문장)",
  "urgent_count": 2,
  "suggestions": ["추천 행동 1", "추천 행동 2"],
  "generated_at": "2026-07-07T09:00:00",
  "cached": false
}
```

## 테스트

```powershell
.venv\Scripts\python -m pytest -v
```

총 **48개** 테스트가 통과한다. `ai_service`가 mock으로 대체되므로 **`ANTHROPIC_API_KEY` 없이도 전체 테스트가 통과**한다. 테스트 DB는 in-memory SQLite로 테스트별로 격리된다. 커버리지는 인증 플로우, 데이터 격리(404), CRUD 및 필터·페이지네이션 경계값, 브리핑(정상·타임아웃·파싱 실패 503·할일 0개·캐시 히트·캐시 무효화)을 포함한다.

## 설계 결정

- **캐시 유효 규칙**: `같은 로컬 날짜 + 같은 fingerprint`. 날이 바뀌거나 대상 할일이 바뀌면 재생성. daily·weekly 동일 규칙.
- **urgent 기준**: 마감 3일 이내 미완료 할일. **이미 지난(overdue) 할일도 포함** — 아직 처리해야 할 일이기 때문.
- **타인 리소스 404**: 접근 권한이 없는 리소스에 403 대신 404를 반환해 리소스의 존재 여부를 노출하지 않는다.
- **naive UTC 저장 규약**: 모든 datetime은 naive UTC로 저장한다. timezone-aware 입력은 UTC로 변환 후 tzinfo를 제거해 정규화한다.
- **시간대**: 날짜/주 경계 계산 기준은 `Asia/Seoul` 고정(설정값 `TIMEZONE`으로 변경 가능).
- **`ai_service` 격리**: LLM 호출을 한 파일에 가둬 테스트 용이성(mock 지점 단일화)과 LLM 교체 용이성을 확보.

## 확장 계획

- **리프레시 토큰 회전**: 현재는 60분 만료 access token만 발급. 리프레시 토큰 회전 도입.
- **PostgreSQL 전환**: `DATABASE_URL` 한 줄(`postgresql+asyncpg://...`)로 전환 가능하도록 이미 async ORM으로 설계됨.
- **브리핑 SSE 스트리밍**: 긴 브리핑을 토큰 단위로 스트리밍 전송.
- **CI**: GitHub Actions로 테스트/린트 자동화.
