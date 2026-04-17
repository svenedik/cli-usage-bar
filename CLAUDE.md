# CLAUDE.md — cli-usage-bar

macOS menu bar app (rumps) that shows live Claude Code + Codex CLI usage.
Python 3.12, managed with `uv`. Always reads local transcripts; Claude path
also does an API-first OAuth fetch with automatic local fallback.

## Commands

```bash
uv run pytest                    # full test suite (tests/)
uv run ruff check src/ tests/    # lint (line-length 100, ruleset E/F/I/B/UP)
uv run python -m cli_usage_bar   # run the menu bar app locally
```

Control command (installed separately, symlinked into `~/.local/bin`):

```bash
usage-bar start | stop | restart | status | logs | config | update | uninstall
```

## Architecture at a glance

- `providers/base.py` — `Provider` ABC with `snapshot() -> UsageSnapshot`,
  `watch_paths()`, optional `preferred_refresh_interval()` and
  `on_manual_refresh()` hooks. Every provider returns a `UsageSnapshot`
  (`models.py`) with `primary` (5h), `secondary` (weekly), optional tokens /
  cost / plan, and a `source` tag (`"api" | "local" | "local-fallback"`).
- `providers/claude_code.py` — local JSONL parser for
  `~/.claude/projects/**/*.jsonl`. ccusage-style 5-hour blocks. Budgets come
  from `config.PLAN_BUDGETS` (empirical, see memory note) with an in-memory
  override set by the auto provider's API calibration.
- `providers/claude_code_api.py` — OAuth call to Anthropic's internal usage
  endpoint (`api.anthropic.com/api/oauth/usage`). Token read from
  `CLAUDE_CODE_OAUTH_TOKEN` or Claude Code's keychain entry. Two retry paths:
  transient errors → 15s; HTTP 429 → `RATE_LIMIT_BACKOFF = 300s`.
- `providers/claude_code_auto.py` — the thing `app.py` actually wires in.
  Runs API + local in parallel, `_merge_api_with_local` overlays API onto
  local (preserves API primary/secondary when present, fills missing windows
  from local), and calls `ClaudeCodeProvider.set_budget_overrides` on success
  to auto-calibrate the offline fallback budget.
- `providers/codex_cli.py` — parses `~/.codex/sessions/**/rollout-*.jsonl`.
  `rate_limits.primary/secondary` are inline in every `token_count` event.
  Drops refresh interval to 15s while a CLI session is actively writing
  (last event < `ACTIVE_SESSION_SECONDS` = 180s).
- `alerts.py` — per-window, per-provider thresholds from config
  (`alert_primary_percent`, `alert_secondary_percent`). Each window fires
  once on crossing and re-arms only when a concrete reading drops below the
  threshold. A missing percent (`pct is None`) is *not* treated as a drop —
  it holds state, so a partial tick can't duplicate the notification.
- `app.py` — rumps lifecycle, timer, menu rendering. `_format_source` writes
  the "source:" menu line with last-sync / last-event timestamps.

## Repo conventions

- Python 3.12 features allowed (`datetime.UTC`, PEP 695 generics like
  `_load_section[T]`).
- Prefer `from __future__ import annotations` in new modules.
- Timestamps: always timezone-aware UTC (`datetime.now(tz=UTC)`).
- Provider side effects (`_last_event_ts`, `_cached`, etc.) are instance
  state; tests inject `now_fn` / fake fetchers rather than patching
  globals. Keep that pattern when adding providers.
- Tests live in `tests/` and use fixtures under `tests/fixtures/`. One file
  per module under test (`test_<module>.py`). No mocks for the database /
  filesystem — use `tmp_path` and real JSONL fixtures.
- Ruff config: line-length 100, ignore E501, selected rules `E/F/I/B/UP`.
- No emojis in source / commit messages / docs unless the user explicitly
  asks.

## Config flow

- `~/.config/cli-usage-bar/config.toml` — user config, generated on first
  run from `config.DEFAULT_CONFIG_TEXT`. Unknown keys are logged + ignored
  (see `_load_section`). When adding a new field, update the default text
  and the dataclass in the same commit.
- `PLAN_BUDGETS` dict holds the empirical Max/Pro 5-hour budgets. Weekly
  pool = `budget * weekly_budget_multiplier` (default 150x).

## Gotchas

- The Anthropic OAuth usage endpoint is **internal, not part of Anthropic's
  public API contract**. If it changes shape, the symptom is "source: local
  (API offline)" for everyone — recovery is usually to flip
  `source = "local"` in config while the parser is updated.
- `_merge_api_with_local` currently uses `api_snap.x or local_snap.x` for
  numeric fields. The API side leaves these as `None` today so the truthy
  fallback is equivalent, but if the API ever returns a real `0`, switch
  that branch to `is not None`.
- Don't add Retry-After header parsing to the 429 path without checking
  what Anthropic actually returns first. The fixed 5-minute cooldown is
  intentional until that's verified.
- Manual "Refresh now" clears the API cache (`_cached = None`, resets
  `_next_retry_at`). Don't introduce another code path that short-circuits
  before `_fetch()` runs on manual refresh or the button becomes a no-op.

## When editing

- Tests + lint are cheap — always run `uv run pytest && uv run ruff check
  src/ tests/` before committing.
- Pre-commit gate runs `code-review:pre-commit-review` on staged changes.
  If the reviewer flags a real regression (not a style nit), fix it before
  the commit rather than filing a follow-up.
- Single focused commits are preferred. A feature + its tests + README
  update belong in the same commit.
