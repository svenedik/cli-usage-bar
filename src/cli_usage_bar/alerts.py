from __future__ import annotations

from dataclasses import dataclass

from cli_usage_bar.models import UsageSnapshot

ALERT_LEVELS = (90, 95)


@dataclass(frozen=True)
class ProviderAlertState:
    last_level: int = 0


@dataclass(frozen=True)
class AlertDecision:
    kind: str
    level: int
    used_percent: float


def next_provider_alert(
    snap: UsageSnapshot,
    state: ProviderAlertState | None,
    *,
    enabled: bool,
) -> tuple[ProviderAlertState, AlertDecision | None]:
    current = state or ProviderAlertState()
    if not enabled:
        return ProviderAlertState(), None
    if snap.error:
        return current, None

    candidates = [
        ("5h", snap.primary),
        ("weekly", snap.secondary),
    ]
    crossed_level = max(
        (
            level
            for level in ALERT_LEVELS
            if any(rl is not None and rl.used_percent >= level for _kind, rl in candidates)
        ),
        default=0,
    )
    if crossed_level == 0:
        return ProviderAlertState(), None
    if current.last_level >= crossed_level:
        return current, None

    eligible = [
        (kind, rl)
        for kind, rl in candidates
        if rl is not None and rl.used_percent >= crossed_level
    ]
    best_kind, best_rl = max(
        eligible,
        key=lambda item: (item[1].used_percent, 1 if item[0] == "5h" else 0),
    )
    return (
        ProviderAlertState(last_level=crossed_level),
        AlertDecision(kind=best_kind, level=crossed_level, used_percent=best_rl.used_percent),
    )
