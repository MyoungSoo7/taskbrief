from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TaskPriority, TaskStatus


def _to_utc_naive(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is not None:
        return v.astimezone(UTC).replace(tzinfo=None)
    return v


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    due_date: datetime | None = None
    priority: TaskPriority = TaskPriority.mid

    _normalize_due = field_validator("due_date")(_to_utc_naive)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    due_date: datetime | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None

    _normalize_due = field_validator("due_date")(_to_utc_naive)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    due_date: datetime | None
    priority: TaskPriority
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
