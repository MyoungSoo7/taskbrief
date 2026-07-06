import enum


class TaskPriority(enum.StrEnum):
    low = "low"
    mid = "mid"
    high = "high"


class TaskStatus(enum.StrEnum):
    todo = "todo"
    doing = "doing"
    done = "done"


class BriefingKind(enum.StrEnum):
    daily = "daily"
    weekly = "weekly"
