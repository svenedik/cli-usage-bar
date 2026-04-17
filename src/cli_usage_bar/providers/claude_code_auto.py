from __future__ import annotations

import logging

from cli_usage_bar.models import UsageSnapshot
from cli_usage_bar.providers.base import Provider
from cli_usage_bar.providers.claude_code import ClaudeCodeProvider
from cli_usage_bar.providers.claude_code_api import ClaudeCodeApiProvider

logger = logging.getLogger(__name__)


class ClaudeCodeAutoProvider(Provider):
    """API-first Claude provider with local fallback."""

    name = "claude_code"

    def __init__(
        self,
        api_provider: ClaudeCodeApiProvider,
        local_provider: ClaudeCodeProvider,
    ) -> None:
        self.api_provider = api_provider
        self.local_provider = local_provider

    def watch_paths(self) -> list[str]:
        return self.local_provider.watch_paths()

    def snapshot(self) -> UsageSnapshot:
        local_snap = self.local_provider.snapshot()
        api_snap = self.api_provider.snapshot()
        if api_snap.ok and (api_snap.primary or api_snap.secondary):
            if local_snap.ok and self._sync_local_calibration(local_snap, api_snap):
                logger.info("updated local Claude calibration from API usage")
            return self._merge_api_with_local(api_snap, local_snap)

        if local_snap.ok:
            if api_snap.error:
                logger.info("Claude API unavailable, using local fallback: %s", api_snap.error)
                return local_snap.model_copy(update={
                    "source": "local-fallback",
                    "last_api_sync": api_snap.last_api_sync,
                })
            return local_snap

        if api_snap.error:
            return api_snap
        return local_snap

    def preferred_refresh_interval(self, default_interval: int) -> int:
        return self.api_provider.preferred_refresh_interval(default_interval)

    def on_manual_refresh(self) -> None:
        self.api_provider.on_manual_refresh()

    @staticmethod
    def _merge_api_with_local(api_snap: UsageSnapshot, local_snap: UsageSnapshot) -> UsageSnapshot:
        """API-preferred snapshot; fall back to local fields when API fields are empty."""
        if not local_snap.ok:
            return api_snap
        uses_local = any(
            (
                api_snap.primary is None and local_snap.primary is not None,
                api_snap.secondary is None and local_snap.secondary is not None,
                api_snap.tokens_used is None and local_snap.tokens_used is not None,
                api_snap.weekly_tokens_used is None and local_snap.weekly_tokens_used is not None,
                api_snap.budget_tokens is None and local_snap.budget_tokens is not None,
                api_snap.weekly_budget_tokens is None and local_snap.weekly_budget_tokens is not None,
                api_snap.cost_usd is None and local_snap.cost_usd is not None,
                api_snap.last_activity is None and local_snap.last_activity is not None,
            )
        )
        api_cost = api_snap.cost_usd
        cost_usd = local_snap.cost_usd if not api_cost else api_cost
        return api_snap.model_copy(update={
            "primary": api_snap.primary or local_snap.primary,
            "secondary": api_snap.secondary or local_snap.secondary,
            "tokens_used": api_snap.tokens_used or local_snap.tokens_used,
            "weekly_tokens_used": api_snap.weekly_tokens_used or local_snap.weekly_tokens_used,
            "budget_tokens": api_snap.budget_tokens or local_snap.budget_tokens,
            "weekly_budget_tokens": api_snap.weekly_budget_tokens or local_snap.weekly_budget_tokens,
            "cost_usd": cost_usd,
            "last_activity": api_snap.last_activity or local_snap.last_activity,
            "source": "mixed" if uses_local else api_snap.source,
        })

    def _sync_local_calibration(self, local_snap: UsageSnapshot, api_snap: UsageSnapshot) -> bool:
        primary_budget = None
        weekly_budget = None

        if (
            local_snap.tokens_used
            and api_snap.primary is not None
            and api_snap.primary.used_percent > 0
        ):
            primary_budget = int(round(local_snap.tokens_used / (api_snap.primary.used_percent / 100.0)))

        if (
            local_snap.weekly_tokens_used
            and api_snap.secondary is not None
            and api_snap.secondary.used_percent > 0
        ):
            weekly_budget = int(
                round(local_snap.weekly_tokens_used / (api_snap.secondary.used_percent / 100.0))
            )

        return self.local_provider.set_budget_overrides(
            primary_budget_tokens=primary_budget,
            weekly_budget_tokens=weekly_budget,
        )
