from fastapi import FastAPI

app = FastAPI(
    title="TaskBrief",
    description="AI 브리핑 기능이 있는 할일 관리 API",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}
