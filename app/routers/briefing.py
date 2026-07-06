from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db import get_session
from app.models import User
from app.schemas.briefing import BriefingRead
from app.services import briefing_service
from app.services.ai_service import BriefingConfigError, BriefingGenerationError

router = APIRouter(prefix="/briefing", tags=["briefing"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


async def _briefing_or_503(session: AsyncSession, user_id: int, kind: str) -> BriefingRead:
    try:
        return await briefing_service.get_briefing(session, user_id, kind)
    except BriefingConfigError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI 기능이 설정되지 않았습니다. 서버에 ANTHROPIC_API_KEY를 설정해주세요.",
        )
    except BriefingGenerationError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI 브리핑 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
        )


@router.get("/daily", response_model=BriefingRead)
async def daily_briefing(user: UserDep, session: SessionDep):
    return await _briefing_or_503(session, user.id, "daily")


@router.get("/weekly", response_model=BriefingRead)
async def weekly_briefing(user: UserDep, session: SessionDep):
    return await _briefing_or_503(session, user.id, "weekly")
