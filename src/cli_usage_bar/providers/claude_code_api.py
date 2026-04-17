"""Claude Code usage provider — OAuth API source.

Uses the same endpoint the Claude.ai dashboard calls internally, so the
returned percentages are dashboard-accurate and never need calibration.

Flow:
- Read the Claude Code OAuth access token from the macOS login keychain
  (service name "Claude Code-credentials"). This is the same credential
  Claude Code itself uses; we do not create, rotate, or persist it.
- GET https://api.anthropic.com/api/oauth/usage with
  ``anthropic-beta: oauth-2025-04-20``.
- Expected response shape (both fields optional):
  {
    "five_hour":  {"utilization": <float 0..100>, "resets_at": <iso-8601>},
    "seven_day":  {"utilization": <float 0..100>, "resets_at": <iso-8601>}
  }

The endpoint is undocumented/beta; if it ever moves or changes shape we
return an ``UsageSnapshot`` with ``error`` set so the menu degrades
gracefully. Consider switching back to ``source = "local"`` if that
happens.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cli_usage_bar.models import RateLimit, UsageSnapshot
from cli_usage_bar.providers.base import Provider

logger = logging.getLogger(__name__)

USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"
BETA_HEADER = "oauth-2025-04-20"

FIVE_HOUR_MINUTES = 5 * 60
SEVEN_DAY_MINUTES = 7 * 24 * 60


class ClaudeCodeApiProvider(Provider):
    name = "claude_code"

    def __init__(
        self,
        plan_display: str | None = None,
        cache_seconds: int = 60,
        now_fn: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
        fetch_fn: Callable[[], dict[str, Any] | None] | None = None,
        token_fn: Callable[[], str | None] | None = None,
    ) -> None:
        self.plan_display = plan_display
        self.cache_seconds = max(0, cache_seconds)
        self._now = now_fn
        self._fetch_fn = fetch_fn
        self._token_fn = token_fn
        self._cached: dict[str, Any] | None = None
        self._cached_at: float = 0.0
        # Last HTTP status from _fetch_live (None = no request made, 0 = transport error)
        self._last_status: int | None = None

    def watch_paths(self) -> list[str]:
        # Nothing to watch on disk — the app's refresh timer polls the API.
        return []

    def snapshot(self) -> UsageSnapshot:
        data = self._fetch()
        if data is None:
            return UsageSnapshot(
                provider=self.name,
                plan_type=self.plan_display,
                error=self._error_message(),
            )
        try:
            primary = _parse_block(data.get("five_hour"), FIVE_HOUR_MINUTES)
            secondary = _parse_block(data.get("seven_day"), SEVEN_DAY_MINUTES)
        except Exception as exc:
            logger.exception("failed to parse oauth usage response")
            return UsageSnapshot(
                provider=self.name,
                plan_type=self.plan_display,
                error=f"api: parse error: {exc}",
            )
        return UsageSnapshot(
            provider=self.name,
            primary=primary,
            secondary=secondary,
            plan_type=self.plan_display,
            last_activity=self._now(),
        )

    def _fetch(self) -> dict[str, Any] | None:
        now = time.time()
        if self._cached is not None and now - self._cached_at < self.cache_seconds:
            return self._cached
        data = (self._fetch_fn or self._fetch_live)()
        if data is not None:
            self._cached = data
            self._cached_at = now
        return data

    def _fetch_live(self) -> dict[str, Any] | None:
        token = (self._token_fn or _read_oauth_token)()
        if not token:
            self._last_status = None
            return None
        req = urllib.request.Request(  # noqa: S310 — fixed https URL, not user input
            USAGE_ENDPOINT,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": BETA_HEADER,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                body = resp.read()
                self._last_status = resp.status
        except urllib.error.HTTPError as exc:
            self._last_status = exc.code
            logger.warning("oauth usage HTTP %s", exc.code)
            return None
        except (urllib.error.URLError, TimeoutError) as exc:
            self._last_status = 0
            logger.warning("oauth usage request failed: %s", exc)
            return None
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("oauth usage response not JSON")
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def _error_message(self) -> str:
        if self._last_status in (401, 403):
            return "api: auth failed (re-login to Claude Code)"
        if self._last_status == 429:
            return "api: rate limited (try again shortly)"
        if self._last_status and self._last_status >= 500:
            return f"api: server error ({self._last_status})"
        return "api: no usage data (missing token or network)"


def _read_oauth_token() -> str | None:
    """Fetch the Claude Code OAuth access token from the login keychain."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=False, timeout=3,
        )
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        blob = json.loads(out.stdout.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(blob, dict):
        return None
    inner = blob.get("claudeAiOauth")
    if isinstance(inner, dict) and inner.get("accessToken"):
        return str(inner["accessToken"])
    if blob.get("accessToken"):
        return str(blob["accessToken"])
    return None


def _parse_block(block: Any, window_minutes: int) -> RateLimit | None:
    if not isinstance(block, dict):
        return None
    if "utilization" not in block or "resets_at" not in block:
        return None
    pct = float(block["utilization"])
    resets_at = _parse_iso(str(block["resets_at"]))
    if resets_at is None:
        return None
    return RateLimit(
        used_percent=max(0.0, min(100.0, pct)),
        window_minutes=window_minutes,
        resets_at=resets_at,
    )


def _parse_iso(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
