<p align="center">
  <img src="assets/logo.jpg" alt="cli-usage-bar logo" width="200" />
</p>

<h1 align="center">cli-usage-bar</h1>

<p align="center">
  A macOS menu bar app that shows <b>live Claude Code and Codex CLI session usage</b><br />
  with Claude API-first sync plus local transcript fallback. No browser cookies, no manual API keys.
</p>

```
 Claude 51% (2h30m) 6% (5d) | Codex 31% (1h10m) 45% (6d) ▾
 ━━ Claude Code ━━
    5h:     ▓▓▓▓▓░░░░░  51.0%  (in 2h30m)
    weekly: ▓░░░░░░░░░   6.0%  (in 5d)
    cost: $4.21  ·  tokens: 3.54M / 6.96M (3.42M left)
    source: API · last API update 14:48
 ━━ Codex CLI ━━
    5h:     ▓▓▓░░░░░░░  31.0%  (in 1h10m)
    weekly: ▓▓▓▓░░░░░░  45.0%  (in 6d)
    plan: plus  ·  tokens: 3,036,637
    source: local · last event 12s ago
    ────────────────────────────────
 Refresh now
 Calibrate Claude Code…
 Claude Usage
 Codex Analytics
 ────────────────────────────────
 Launch at login ✓
 Open config
 Copy diagnostic info
 About v0.1.0
 Quit
```

## Features

- Live **5h** and **weekly** usage for Claude Code + Codex CLI in one place.
- Configurable menu bar title: pick your own label, show/hide 5h / weekly
  percentages, optionally append remaining time (`"Claude 51% (2h30m)"`).
- **Smart alerts** — native macOS notifications when 5-hour or weekly usage
  crosses per-provider, per-window thresholds (default `90%` / `95%`, each fires
  once and re-arms when usage drops below the threshold; set to `0` to disable).
- **Source transparency** — each provider's menu shows whether the current data
  came from the API, local transcripts, or a mixed snapshot, and when it was
  last refreshed (`source: API · last API update 14:48`, `source: mixed (API + local)`,
  `source: local · last event 12s ago`).
- **Quick links** to the Claude.ai and ChatGPT dashboards.
- **Launch at login** toggle from the menu (no need to touch `launchctl`).
- **Copy diagnostic info** button: version, config, provider state and recent
  logs onto your clipboard in one click — ideal for filing GitHub issues.
- **Calibrate Claude Code** against the real dashboard percent to correct
  plan-budget estimates.
- **Claude API first**: `source = "api"` is the default and uses Claude
  Code's existing OAuth auth when available, with automatic local fallback if
  the usage endpoint is unavailable.
- Codex CLI is always fully offline (rate limits are inline in the rollout).

## Install (one-liner)

```bash
curl -fsSL https://raw.githubusercontent.com/svenedik/cli-usage-bar/main/install.sh | bash
```

This does four things:

1. clones the repo into `~/.local/share/cli-usage-bar`
2. installs Python deps with [`uv`](https://github.com/astral-sh/uv)
3. registers a `LaunchAgent` so the app starts at login
4. installs a control command `usage-bar` at `~/.local/bin/usage-bar`

Make sure `~/.local/bin` is in your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"   # add to ~/.zshrc or ~/.bashrc
```

## Control it

Everything is a single short command:

```bash
usage-bar start        # start the app
usage-bar stop         # stop the app
usage-bar restart      # pick up code / config changes
usage-bar status       # running (pid 23979) | stopped
usage-bar logs         # tail -f /tmp/cli-usage-bar.log
usage-bar config       # open ~/.config/cli-usage-bar/config.toml
usage-bar update       # git pull + deps + restart
usage-bar uninstall    # remove LaunchAgent + install dir
usage-bar help
```

After editing `config.toml`, just click **Refresh now** in the menu (picks up
title/label changes) or run `usage-bar restart` (also picks up `enabled`,
`plan`, budget changes).

## How it works

cli-usage-bar always reads local transcript files for Claude Code and Codex
CLI. For Claude, the default mode is API-first:

- **Claude Code** (default `source = "api"`) — first tries Anthropic's
  internal OAuth usage endpoint for dashboard-exact percentages. If that
  request fails because of auth, network, or rate limiting, the app
  automatically falls back to local transcript parsing so the menu bar keeps
  showing usage instead of an error. While API mode is healthy, the app also
  auto-calibrates the local fallback budget in memory from the exact API
  percentage.
- **Claude Code** (`source = "local"`) —
  `~/.claude/projects/<slug>/<session-id>.jsonl`. Token counts from every
  assistant message are aggregated into rolling 5-hour "blocks"
  (ccusage-style) and divided by a plan budget estimate. Because Anthropic
  doesn't publish exact budgets, this can drift a few percent from the
  dashboard (see **Calibrate** below).
- **Codex CLI** — `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Every
  `token_count` event already contains inline `rate_limits.primary` (5-hour)
  and `rate_limits.secondary` (weekly) percentages — we just render them.
  Always offline. While a Codex CLI session is actively writing events
  (last event under 3 minutes old) the app drops its refresh interval to
  15 seconds so new token counts surface quickly; it returns to the default
  `refresh_interval_sec` when the session goes idle.

Benefits:

- API-first mode gives exact dashboard numbers when Anthropic allows it, and
  local fallback when it doesn't.
- Local mode stays 100% offline. No cookie extraction, no API key management.
- Works whether you use Claude Code / Codex CLI via Pro, Max, Plus, etc.
- Trivial data schema — trivial to extend with a new provider.

## FAQ

**Do I need an API key or token?**
No manual token pasting is needed. In the default `source = "api"` mode the
app reuses the OAuth token that Claude Code already configured (from
`CLAUDE_CODE_OAUTH_TOKEN` or Claude Code's own macOS keychain entry). If you
switch to `source = "local"`, the app stays fully offline.

**Does it send my data anywhere?**
The app always reads local files:

- `~/.claude/projects/**/*.jsonl` (Claude Code transcripts)
- `~/.codex/sessions/**/rollout-*.jsonl` (Codex CLI rollouts)
- `~/.config/cli-usage-bar/config.toml` (your settings)

and writes to `~/.config/cli-usage-bar/config.toml` (only when you click
Calibrate) and `/tmp/cli-usage-bar.log` (app logs).

In the default `source = "api"` mode it additionally makes an HTTPS GET to
`api.anthropic.com/api/oauth/usage` every `api_cache_seconds` (default 600s),
authenticated with your existing Claude Code OAuth token. If the request
fails, the app falls back to local transcript data automatically. In
`source = "local"` mode there are no network requests.

**Do I need to sign into Claude or ChatGPT in this app?**
No extra sign-in happens inside this app. `source = "api"` reuses the Claude
Code auth you already set up on that Mac, and `source = "local"` works with no
network login at all.

**What if I only use one of the two?**
Set the other provider's `enabled = false` in the config and
`usage-bar restart`.

## Configuration

First run creates `~/.config/cli-usage-bar/config.toml`. All fields are
optional; the generated defaults are shown below.

```toml
[general]
refresh_interval_sec = 60
show_title_percent = true          # master switch for menu bar percentages

[claude_code]
enabled = true
plan = "max5"                    # pro | max5 | max20 | custom
custom_budget_tokens = 0         # only used when plan = "custom"
weekly_budget_multiplier = 150.0 # weekly pool size relative to the 5-hour block
title_label = "C"                # prefix shown in the menu bar title
title_show_primary = true        # include the 5-hour percent in the title
title_show_secondary = false     # include the weekly percent in the title
title_show_reset = false         # append remaining time next to each percent
alert_primary_percent = 90       # notify when 5h % crosses this (0 = disabled)
alert_secondary_percent = 95     # notify when weekly % crosses this (0 = disabled)
plan_label = ""                  # optional label, e.g. "Max (5x)"; empty = auto
source = "api"                   # default: exact OAuth usage with automatic local fallback
api_cache_seconds = 600          # cache for "api" mode (seconds)

[codex_cli]
enabled = true
title_label = "X"                # prefix shown in the menu bar title
title_show_primary = true        # include the 5-hour percent in the title
title_show_secondary = false     # include the weekly percent in the title
title_show_reset = false         # append remaining time next to each percent
alert_primary_percent = 90       # notify when 5h % crosses this (0 = disabled)
alert_secondary_percent = 95     # notify when weekly % crosses this (0 = disabled)
```

### Claude Source Mode

Claude uses API-first mode by default:

```toml
[claude_code]
source = "api"
api_cache_seconds = 600
```

This reuses your existing Claude Code login, tries the dashboard-exact usage
endpoint first, and falls back to local transcript parsing if the endpoint is
unavailable. Transient errors (network, 5xx) are retried every 15 seconds until
the API recovers. If Anthropic responds with `429 Too Many Requests`, the app
backs off for 5 minutes before trying again so it doesn't extend the cooldown
window. Once the API succeeds it returns to the slower cached polling cadence.
Local transcript parsing keeps running in the background the whole time, and
its view is merged into the menu whenever the API returns a partial payload.

If you want fully offline behavior instead:

```toml
[claude_code]
source = "local"
```

### Alerts

Each provider has two configurable thresholds — one for the 5-hour window
(`alert_primary_percent`, default `90`) and one for the weekly window
(`alert_secondary_percent`, default `95`). When usage crosses either threshold
you get a single native macOS notification for that window; it won't re-fire
until usage drops below the threshold again.

Example notification:

```
Claude Code · 5h
Usage at 91% (threshold 90%).
```

Set a threshold to `0` to disable that window entirely, e.g. to silence weekly
alerts while keeping the 5-hour alert:

```toml
[codex_cli]
alert_primary_percent = 80       # alert earlier for the 5h block
alert_secondary_percent = 0      # never alert on weekly
```

### Using only one CLI?

Set the other provider's `enabled = false`, then `usage-bar restart`. Title
becomes just `Claude 51%` or `Codex 31%` with no separator.

### Dashboard-accurate mode (`source = "api"`)

`source = "api"` is the default. It uses dashboard-exact values when the
endpoint is available, with automatic local fallback when it is not.

If you want to tune its polling interval, set:

```toml
[claude_code]
source = "api"
api_cache_seconds = 600
```

and `usage-bar restart`. The app will:

1. Reuse your existing Claude Code OAuth token from
   `CLAUDE_CODE_OAUTH_TOKEN` or Claude Code's current macOS keychain entry.
2. Call Anthropic's usage endpoint every `api_cache_seconds`
   (default 600s, cached between calls to stay well under rate limits).
3. If the API path fails with a transient error, retry every 15 seconds.
4. If Anthropic returns `429`, back off for 5 minutes before retrying so the
   cooldown window isn't extended.
5. Keep local transcript parsing running in the background the whole time.
6. Use successful API reads to auto-calibrate the local fallback budget.
7. Fall back to local transcript-based numbers if the endpoint fails.
8. Even during fallback, merge any partial API fields (e.g. weekly) over the
   local view, and keep the source line up to date (`source: mixed (API +
   local)` for partial merges, `source: local (API offline)` when the API path
   is down). Clicking **Refresh now** invalidates the API cache and forces a
   fresh fetch immediately.

Requirements:

- `claude auth status` shows you're signed in. If not, run
  `claude auth login --claudeai` first.
- Network access to `api.anthropic.com`.

Notes:

- No manual token pasting. Calibration is disabled in this mode (percentages
  come from the source of truth whenever the API path succeeds).
- The endpoint is the same internal one the dashboard uses and isn't part
  of Anthropic's public API contract, so in theory it could change. If it
  ever does, flip back to `source = "local"`.

### Calibrating the Claude Code percent (local mode only)

Anthropic doesn't publish 5-hour block budgets, so `source = "local"`
defaults are estimates. If your menu bar `5h %` disagrees with the
Claude.ai dashboard and you'd rather stay offline:

1. Click **Calibrate Claude Code…** in the menu
2. Enter the percent shown in Claude.ai → Settings → Usage
3. The app solves for your real budget and writes `plan = "custom"` +
   `custom_budget_tokens` back to the config

(If you're already in `source = "api"` mode the menu shows "Calibration not
needed" — the API returns exact percentages.)

Codex CLI doesn't need calibration — percentages are inline in the rollout.

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.12+ (installed automatically by `uv`)
- `uv` — <https://github.com/astral-sh/uv>

## Manual install (no one-liner)

```bash
git clone https://github.com/svenedik/cli-usage-bar.git
cd cli-usage-bar
uv sync --no-dev

# LaunchAgent so it starts at login
sed -e "s|{{INSTALL_DIR}}|$PWD|g" -e "s|{{HOME}}|$HOME|g" \
    packaging/com.svenedik.cli-usage-bar.plist \
    > ~/Library/LaunchAgents/com.svenedik.cli-usage-bar.plist
launchctl load ~/Library/LaunchAgents/com.svenedik.cli-usage-bar.plist

# Control command on PATH
mkdir -p ~/.local/bin
ln -sf "$PWD/bin/usage-bar" ~/.local/bin/usage-bar
```

## Troubleshooting

- **Icon doesn't appear** — `usage-bar status` should say "running". If it
  says "stopped", run `usage-bar start`. Logs: `usage-bar logs`.
- **`Claude Code: no recent usage messages`** — you haven't used Claude Code
  in the last 24 hours, or `~/.claude/projects` isn't populated.
- **`Codex CLI: no rollout files found`** — you haven't run `codex` yet.
- **Percentage looks wrong for Claude Code** — use **Calibrate Claude Code…**
  or edit `plan` / `custom_budget_tokens` in the config and `usage-bar restart`.
  For byte-exact values switch to `source = "api"` (see above).
- **`api: no usage data (missing token or network)`** — you're in
  `source = "api"` mode but no OAuth token was available from Claude Code's
  configured auth or `api.anthropic.com` is unreachable. You can always fall
  back to `source = "local"`.
- **`api: Claude login required (run `claude auth login --claudeai`)`** —
  Claude Code is not currently signed in on this Mac. Complete the login once,
  then `usage-bar restart`.
- **`api: OAuth token unreadable (re-login to Claude Code)`** — Claude Code
  reports a login exists, but the menu app could not read the OAuth token from
  the current env/keychain setup. Re-run `claude auth login --claudeai`, then
  restart the app.
- **`api: auth failed (run `claude auth login --claudeai`)`** — the upstream
  endpoint rejected the token. Sign into Claude Code again and the menu will
  recover on the next refresh.
- **`api: rate limited (try again shortly)`** — upstream `429`. The app keeps
  the local fallback visible and waits 5 minutes before retrying the API path
  so it doesn't extend the cooldown. Click **Refresh now** to force an early
  retry.

## Development

```bash
uv sync
uv run pytest
uv run ruff check
uv run python -m cli_usage_bar
```

The app is a single `rumps.App`. Providers implement the `Provider` ABC and
produce a `UsageSnapshot`; adding a third provider is a matter of one file and
one test fixture.

## License

MIT — see [LICENSE](./LICENSE).

## Acknowledgements

- Inspiration: [BOUSHABAMohammed/claude-bar](https://github.com/BOUSHABAMohammed/claude-bar)
  (Claude.ai web usage) and [steipete/CodexBar](https://github.com/steipete/CodexBar).
- 5-hour block algorithm inspired by [ryoppippi/ccusage](https://github.com/ryoppippi/ccusage).
