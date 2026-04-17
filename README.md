# cli-usage-bar

A macOS menu bar app that shows **live Claude Code and Codex CLI session usage**
by reading local transcript files. No login, no browser cookies, no API keys.

```
 AI ▾
 ━━ Claude Code ━━
    5h:     ▓▓░░░░░░░░  17.4%  (in 3h21m)
    weekly: ▓░░░░░░░░░   4.2%  (in 6d)
    cost: $4.21  ·  tokens: 38,241,112
 ━━ Codex CLI ━━
    5h:     ▓▓▓░░░░░░░  30.0%  (in 4h12m)
    weekly: ▓▓▓▓░░░░░░  38.0%  (in 3d)
    plan: plus  ·  tokens: 3,036,637
    ────────────────────────────────
 Refresh now
 Open config
 About v0.1.0
 Quit
```

## How it works

Instead of calling a web API, cli-usage-bar reads the transcript files the CLIs
already write to disk:

- **Claude Code** — `~/.claude/projects/<slug>/<session-id>.jsonl`. Token
  counts from every assistant message are aggregated into rolling 5-hour
  "blocks", ccusage-style.
- **Codex CLI** — `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Every
  `token_count` event already contains inline `rate_limits.primary` (5-hour)
  and `rate_limits.secondary` (weekly) percentages — we just render them.

Benefits:

- 100% offline. No cookie extraction, no API authentication.
- Works whether you use Claude Code / Codex CLI via Pro, Max, Plus, etc.
- Trivial data schema — trivial to extend with a new provider.

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.12+ (installed automatically by `uv`)
- `uv` — <https://github.com/astral-sh/uv>

## Install

### One-liner

```bash
curl -fsSL https://raw.githubusercontent.com/svenedik/cli-usage-bar/main/install.sh | bash
```

This clones the repo into `~/.local/share/cli-usage-bar`, installs deps with
`uv`, sets up a `LaunchAgent` so it starts at login, and launches the app.

### Manual installation

```bash
git clone https://github.com/svenedik/cli-usage-bar.git
cd cli-usage-bar
uv sync --no-dev
uv run cli-usage-bar
```

To make it start automatically at login:

```bash
sed -e "s|{{INSTALL_DIR}}|$PWD|g" -e "s|{{HOME}}|$HOME|g" \
    packaging/com.svenedik.cli-usage-bar.plist \
    > ~/Library/LaunchAgents/com.svenedik.cli-usage-bar.plist
launchctl load ~/Library/LaunchAgents/com.svenedik.cli-usage-bar.plist
```

## Configuration

First run creates `~/.config/cli-usage-bar/config.toml` with defaults:

```toml
[general]
refresh_interval_sec = 60
show_title_percent = true        # shows "C 17% | X 30%" in the menu bar title

[claude_code]
enabled = true
plan = "max20"                    # "pro" | "max5" | "max20" | "custom"
custom_budget_tokens = 0          # used only when plan = "custom"

[codex_cli]
enabled = true
```

The `plan` value maps to the approximate per-block token budget used to
compute the Claude Code "5h %" value. Adjust to your subscription — Codex CLI
doesn't need this because the rate-limit percentage is already in the rollout
file.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.svenedik.cli-usage-bar.plist
rm ~/Library/LaunchAgents/com.svenedik.cli-usage-bar.plist
rm -rf ~/.local/share/cli-usage-bar
rm -rf ~/.config/cli-usage-bar
```

## Troubleshooting

- **Icon doesn't appear** — check `/tmp/cli-usage-bar.log`. The most common
  cause is that the `AI` title is visible but the bar is squeezed off-screen
  by other menubar items; try hiding some.
- **`Claude Code: no recent usage messages`** — you haven't used Claude Code
  in the last 24 hours, or `~/.claude/projects` isn't populated.
- **`Codex CLI: no rollout files found`** — you haven't run `codex` yet, or
  the sessions directory is at a non-default location.
- **Percentage looks wrong for Claude Code** — adjust `plan` in
  `config.toml` or set `plan = "custom"` and a `custom_budget_tokens` value.

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
