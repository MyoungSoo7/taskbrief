from fastapi import FastAPI

from app.routers import auth, tasks

app = FastAPI(
    title="TaskBrief",
    description="AI 브리핑 기능이 있는 할일 관리 API",
    version="0.1.0",
)

app.include_router(auth.router)
app.include_router(tasks.router)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}
