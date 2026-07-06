from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.models.enums import TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate


async def create_task(session: AsyncSession, user_id: int, data: TaskCreate) -> Task:
    task = Task(user_id=user_id, **data.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    user_id: int,
    status: TaskStatus | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[Task]:
    stmt = select(Task).where(Task.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Task.status == status.value)
    if due_before is not None:
        stmt = stmt.where(Task.due_date != None, Task.due_date <= due_before)  # noqa: E711
    if due_after is not None:
        stmt = stmt.where(Task.due_date != None, Task.due_date >= due_after)  # noqa: E711
    stmt = stmt.order_by(Task.id).offset(offset).limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_task(session: AsyncSession, user_id: int, task_id: int) -> Task | None:
    """본인 소유가 아니면 None (라우터에서 404 — 존재 여부 비노출)."""
    return await session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))


async def update_task(session: AsyncSession, task: Task, data: TaskUpdate) -> Task:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task: Task) -> None:
    await session.delete(task)
    await session.commit()
