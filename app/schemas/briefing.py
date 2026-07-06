from datetime import datetime

from pydantic import BaseModel


class BriefingRead(BaseModel):
    summary: str
    urgent_count: int
    suggestions: list[str]
    generated_at: datetime
    cached: bool
