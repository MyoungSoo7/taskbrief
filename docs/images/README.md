# 이미지 애셋

README의 "데모" 섹션에서 참조하는 스크린샷·GIF를 이 폴더에 둔다.

| 파일명 | 내용 | 캡처 방법 |
|---|---|---|
| `swagger-ui.png` | Swagger UI 전체 엔드포인트 목록 | 서버 실행 후 `http://127.0.0.1:8000/docs` 를 열고 전체 화면 캡처 |
| `briefing-response.png` | `/briefing/daily` 응답 예시 | Swagger에서 `/briefing/daily` 를 실행한 뒤 응답(200 또는 503) 부분 캡처 |
| `demo.gif` | 로그인 → 할일 생성 → 브리핑 요청 흐름 | 화면 녹화 도구로 짧게(10~20초) 녹화 후 GIF 변환 |

## 캡처 절차

```powershell
# 1. 서버 실행 (실제 브리핑을 보려면 .env에 ANTHROPIC_API_KEY 설정)
Copy-Item .env.example .env
.venv\Scripts\alembic upgrade head
.venv\Scripts\uvicorn app.main:app --reload

# 2. 브라우저에서 http://127.0.0.1:8000/docs 접속
#    - Authorize 버튼으로 로그인(회원가입 → 로그인으로 토큰 발급) 후
#      각 엔드포인트를 "Try it out"으로 실행하며 캡처
```

**GIF 녹화 도구**: Windows는 [ScreenToGif](https://www.screentogif.com/)(무료)가 간편하다. 녹화 → GIF로 저장 → 이 폴더에 `demo.gif`로 저장.

## 활성화

파일을 넣은 뒤, 루트 `README.md`의 "데모" 섹션에 있는 주석 처리된 이미지 마크다운의 `<!-- -->` 를 제거하면 표시된다. 커밋 전 이미지 용량은 되도록 1MB 이하(GIF는 5MB 이하)로 최적화할 것.
