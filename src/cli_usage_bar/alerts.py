from __future__ import annotations

from dataclasses import dataclass

from cli_usage_bar.models import UsageSnapshot


@dataclass(frozen=True)
class ProviderAlertState:
    primary_fired: bool = False
    secondary_fired: bool = False


@dataclass(frozen=True)
class AlertDecision:
    kind: str
    level: int
    used_percent: float


def next_provider_alert(
    snap: UsageSnapshot,
    state: ProviderAlertState | None,
    *,
    primary_threshold: int,
    secondary_threshold: int,
) -> tuple[ProviderAlertState, AlertDecision | None]:
    """Decide whether to fire a notification for this provider.

    Each window fires **once** when it first crosses its threshold and re-arms
    only after usage drops back below the threshold. ``threshold <= 0`` disables
    that window's alert.
    """
    current = state or ProviderAlertState()
    if snap.error:
        return current, None

    primary_pct = snap.primary.used_percent if snap.primary else None
    secondary_pct = snap.secondary.used_percent if snap.secondary else None

    # A missing percent (``pct is None``) means "no new info" — we keep the
    # previous fired flag so a single partial tick does not re-arm and cause a
    # duplicate notification on the next healthy read.
    primary_fired = current.primary_fired
    if primary_threshold <= 0:
        primary_fired = False
    elif primary_pct is not None and primary_pct < primary_threshold:
        primary_fired = False

    secondary_fired = current.secondary_fired
    if secondary_threshold <= 0:
        secondary_fired = False
    elif secondary_pct is not None and secondary_pct < secondary_threshold:
        secondary_fired = False

    if (
        primary_threshold > 0
        and primary_pct is not None
        and primary_pct >= primary_threshold
        and not primary_fired
    ):
        return (
            ProviderAlertState(primary_fired=True, secondary_fired=secondary_fired),
            AlertDecision(kind="5h", level=primary_threshold, used_percent=primary_pct),
        )

    if (
        secondary_threshold > 0
        and secondary_pct is not None
        and secondary_pct >= secondary_threshold
        and not secondary_fired
    ):
        return (
            ProviderAlertState(primary_fired=primary_fired, secondary_fired=True),
            AlertDecision(kind="weekly", level=secondary_threshold, used_percent=secondary_pct),
        )

    return ProviderAlertState(primary_fired=primary_fired, secondary_fired=secondary_fired), None
