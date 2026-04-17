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
- Everything lives on disk — no login, no tokens, no network requests.

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

Instead of calling a web API, cli-usage-bar reads the transcript files the CLIs
already write to disk:

- **Claude Code** — `~/.claude/projects/<slug>/<session-id>.jsonl`. Token
  counts from every assistant message are aggregated into rolling 5-hour
  "blocks" (ccusage-style).
- **Codex CLI** — `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Every
  `token_count` event already contains inline `rate_limits.primary` (5-hour)
  and `rate_limits.secondary` (weekly) percentages — we just render them.

Benefits:

- 100% offline. No cookie extraction, no API authentication.
- Works whether you use Claude Code / Codex CLI via Pro, Max, Plus, etc.
- Trivial data schema — trivial to extend with a new provider.

## FAQ

**Do I need an API key or token?**
No. The app reads files the CLIs already write on your machine. It never talks
to any server, never reads cookies, never asks for a password. If a file
doesn't exist (you haven't used Claude Code or Codex), the corresponding
section just shows "not configured".

**Does it send my data anywhere?**
No. It only reads:

- `~/.claude/projects/**/*.jsonl` (Claude Code transcripts)
- `~/.codex/sessions/**/rollout-*.jsonl` (Codex CLI rollouts)
- `~/.config/cli-usage-bar/config.toml` (your settings)

and writes to `~/.config/cli-usage-bar/config.toml` (only when you click
Calibrate) and `/tmp/cli-usage-bar.log` (app logs). No network requests.

**Do I need to sign into Claude or ChatGPT in this app?**
No. You're already signed in inside Claude Code / Codex CLI; that's all it
needs. This app is just a reader of their on-disk state.

**What if I only use one of the two?**
Set the other provider's `enabled = false` in the config and
`usage-bar restart`.

## Configuration

First run creates `~/.config/cli-usage-bar/config.toml`. All fields are
optional; defaults are documented inline.

```toml
[general]
refresh_interval_sec = 60
show_title_percent = true          # master switch for the menu bar title

[claude_code]
enabled = true                     # false → hide Claude Code entirely
plan = "max5"                      # "pro" | "max5" | "max20" | "custom"
custom_budget_tokens = 0           # only when plan = "custom"
weekly_budget_multiplier = 150.0   # weekly pool relative to 5h block
title_label = "Claude"             # prefix in the menu bar title
title_show_primary = true          # show 5h percent
title_show_secondary = false       # show weekly percent
title_show_reset = false           # append remaining time, e.g. "51% (2h30m)"
alert_primary_percent = 0          # notify when 5h crosses this (0 = off)
alert_secondary_percent = 0        # notify when weekly crosses this (0 = off)
plan_label = ""                    # e.g. "Max (5x)"; "" auto-derives from plan

[codex_cli]
enabled = true                     # false → hide Codex CLI entirely
title_label = "Codex"
title_show_primary = true
title_show_secondary = false
title_show_reset = false
alert_primary_percent = 0
alert_secondary_percent = 0
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

### Calibrating the Claude Code percent

Anthropic doesn't publish 5-hour block budgets, so defaults are estimates. If
your menu bar `5h %` disagrees with the Claude.ai dashboard:

1. Click **Calibrate Claude Code…** in the menu
2. Enter the percent shown in Claude.ai → Settings → Usage
3. The app solves for your real budget and writes `plan = "custom"` +
   `custom_budget_tokens` back to the config

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
