<p align="center">
  <img src="assets/logo.jpg" alt="cli-usage-bar logo" width="200" />
</p>

<h1 align="center">cli-usage-bar</h1>

<p align="center">
  A macOS menu bar app that shows <b>live Claude Code and Codex CLI session usage</b><br />
  by reading local transcript files. No login, no browser cookies, no API keys.
</p>

```
 Claude 51% (2h30m) 6% (5d) | Codex 31% (1h10m) 45% (6d) ▾
 ━━ Claude Code ━━
    5h:     ▓▓▓▓▓░░░░░  51.0%  (in 2h30m)
    weekly: ▓░░░░░░░░░   6.0%  (in 5d)
    cost: $4.21  ·  tokens: 3.54M / 6.96M (3.42M left)
 ━━ Codex CLI ━━
    5h:     ▓▓▓░░░░░░░  31.0%  (in 1h10m)
    weekly: ▓▓▓▓░░░░░░  45.0%  (in 6d)
    plan: plus  ·  tokens: 3,036,637
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
- **Threshold alerts** — native macOS notifications when usage crosses a
  configurable percent (once per block).
- **Quick links** to the Claude.ai and ChatGPT dashboards.
- **Launch at login** toggle from the menu (no need to touch `launchctl`).
- **Copy diagnostic info** button: version, config, provider state and recent
  logs onto your clipboard in one click — ideal for filing GitHub issues.
- **Calibrate Claude Code** against the real dashboard percent to correct
  plan-budget estimates.
- **Two Claude Code modes**: offline (default, JSONL-based) or
  dashboard-accurate (`source = "api"`, reuses Claude Code's own OAuth token
  from the macOS keychain — no extra login).
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

By default, cli-usage-bar reads the transcript files the CLIs already write to
disk — no network calls, no login, no cookies:

- **Claude Code** (default `source = "local"`) —
  `~/.claude/projects/<slug>/<session-id>.jsonl`. Token counts from every
  assistant message are aggregated into rolling 5-hour "blocks"
  (ccusage-style) and divided by a plan budget estimate. Because Anthropic
  doesn't publish exact budgets, this can drift a few percent from the
  dashboard (see **Calibrate** below).
- **Claude Code** (optional `source = "api"`) — reuses the OAuth token that
  Claude Code already stored in the macOS keychain and calls Anthropic's
  internal usage endpoint, the same one the dashboard uses. Percentages are
  byte-identical to `claude.ai → Settings → Usage`, no calibration needed.
  You never paste a token; you just need to be logged into Claude Code.
- **Codex CLI** — `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Every
  `token_count` event already contains inline `rate_limits.primary` (5-hour)
  and `rate_limits.secondary` (weekly) percentages — we just render them.
  Always offline.

Benefits:

- Default mode is 100% offline. No cookie extraction, no API key management.
- Optional API mode uses your existing login — still no manual auth step.
- Works whether you use Claude Code / Codex CLI via Pro, Max, Plus, etc.
- Trivial data schema — trivial to extend with a new provider.

## FAQ

**Do I need an API key or token?**
No. In the default `source = "local"` mode the app never talks to any server,
never reads cookies, never asks for a password. In the optional
`source = "api"` mode it reuses the OAuth token that Claude Code already
stored in your macOS keychain (under `Claude Code-credentials`) — you don't
paste anything, you just need to be logged into Claude Code.

**Does it send my data anywhere?**
In default mode it only reads local files:

- `~/.claude/projects/**/*.jsonl` (Claude Code transcripts)
- `~/.codex/sessions/**/rollout-*.jsonl` (Codex CLI rollouts)
- `~/.config/cli-usage-bar/config.toml` (your settings)

and writes to `~/.config/cli-usage-bar/config.toml` (only when you click
Calibrate) and `/tmp/cli-usage-bar.log` (app logs). **No network requests in
this mode.**

In optional `source = "api"` mode it additionally makes an HTTPS GET to
`api.anthropic.com/api/oauth/usage` every `api_cache_seconds` (default 60s),
authenticated with your existing Claude Code OAuth token. Nothing else is
sent; no other endpoint is called.

**Do I need to sign into Claude or ChatGPT in this app?**
No. You're already signed in inside Claude Code / Codex CLI; that's all it
needs. This app is just a reader of their on-disk state (and, in API mode,
their existing OAuth session).

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
alert_primary_percent = 0        # notify when 5-hour usage reaches this percent
alert_secondary_percent = 0      # notify when weekly usage reaches this percent
plan_label = ""                  # optional label, e.g. "Max (5x)"; empty = auto
source = "local"                 # "local" (offline JSONL) | "api" (OAuth usage endpoint)
api_cache_seconds = 60           # cache for "api" mode (seconds)

[codex_cli]
enabled = true
title_label = "X"                # prefix shown in the menu bar title
title_show_primary = true        # include the 5-hour percent in the title
title_show_secondary = false     # include the weekly percent in the title
title_show_reset = false         # append remaining time next to each percent
alert_primary_percent = 0        # notify when 5-hour usage reaches this percent
alert_secondary_percent = 0      # notify when weekly usage reaches this percent
```

### Alerts

Set `alert_primary_percent = 80` (or any threshold) and when the
corresponding percent first crosses it, you'll get a native macOS
notification like:

```
Claude Code · 5h
Usage at 80% (threshold 80%).
```

The alert fires at most once per block and re-arms when the block resets,
so you won't get spammed. Weekly thresholds work the same way via
`alert_secondary_percent`.

### Using only one CLI?

Set the other provider's `enabled = false`, then `usage-bar restart`. Title
becomes just `Claude 51%` or `Codex 31%` with no separator.

### Dashboard-accurate mode (`source = "api"`)

In the default `"local"` mode the 5-hour percent is estimated from local
JSONL token counts, which can drift a few percent from the dashboard.

If you want the exact same number Claude.ai shows, set:

```toml
[claude_code]
source = "api"
api_cache_seconds = 60
```

and `usage-bar restart`. The app will:

1. Read your existing Claude Code OAuth token from the macOS keychain
   (`security find-generic-password -s "Claude Code-credentials"`).
2. Call Anthropic's usage endpoint every `api_cache_seconds`
   (default 60s, cached between calls to stay well under any rate limit).
3. Render the returned 5-hour and 7-day `utilization` directly.

Requirements:

- You've signed into Claude Code at least once on this Mac (the token is
  what `claude` itself uses).
- Network access to `api.anthropic.com`.

Notes:

- No manual token pasting. Calibration is disabled in this mode (percentages
  come from the source of truth).
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
  `source = "api"` mode but the keychain entry `Claude Code-credentials`
  isn't present (sign into Claude Code once) or `api.anthropic.com` is
  unreachable. You can always fall back to `source = "local"`.
- **`api: auth failed (re-login to Claude Code)`** — the keychain token
  has expired or been revoked. Sign into Claude Code again (it refreshes
  the same keychain entry) and the menu will recover on the next refresh.
- **`api: rate limited (try again shortly)`** — upstream `429`. Increase
  `api_cache_seconds` if you see this often.

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
