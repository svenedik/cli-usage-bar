from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RateLimit(BaseModel):
    used_percent: float = Field(ge=0.0)
    window_minutes: int = Field(gt=0)
    resets_at: datetime

    def seconds_until_reset(self, now: datetime) -> int:
        delta = (self.resets_at - now).total_seconds()
        return max(0, int(delta))


class UsageSnapshot(BaseModel):
    provider: str
    primary: RateLimit | None = None
    secondary: RateLimit | None = None
    plan_type: str | None = None
    tokens_used: int | None = None
    weekly_tokens_used: int | None = None
    budget_tokens: int | None = None           # 5h block budget (if known)
    weekly_budget_tokens: int | None = None    # 7-day budget (if known)
    cost_usd: float | None = None
    last_activity: datetime | None = None
    source: str | None = None                  # "api" | "local" | "local-fallback" | "mixed"
    last_api_sync: datetime | None = None      # set on successful API fetches
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
