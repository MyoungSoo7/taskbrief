from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db import get_session
from app.models import User
from app.models.enums import TaskStatus
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_current_user)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskRead)
async def create_task(payload: TaskCreate, user: UserDep, session: SessionDep):
    return await task_service.create_task(session, user.id, payload)


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    user: UserDep,
    session: SessionDep,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await task_service.list_tasks(
        session, user.id, status_filter, due_before, due_after, offset, limit
    )
