import enum


class TaskPriority(str, enum.Enum):
    low = "low"
    mid = "mid"
    high = "high"


class TaskStatus(str, enum.Enum):
    todo = "todo"
    doing = "doing"
    done = "done"


class BriefingKind(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
