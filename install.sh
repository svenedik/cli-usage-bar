#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/svenedik/cli-usage-bar.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/cli-usage-bar}"
LAUNCH_AGENT_NAME="com.svenedik.cli-usage-bar"
PLIST_SRC="$INSTALL_DIR/packaging/${LAUNCH_AGENT_NAME}.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${LAUNCH_AGENT_NAME}.plist"

info()  { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m!!\033[0m %s\n" "$*"; }
die()   { printf "\033[1;31mxx\033[0m %s\n" "$*" >&2; exit 1; }

[[ "$(uname)" == "Darwin" ]] || die "cli-usage-bar only supports macOS."

if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  info "Updating existing install at $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only
else
  info "Cloning $REPO_URL → $INSTALL_DIR"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

info "Installing Python dependencies (uv sync)"
(cd "$INSTALL_DIR" && uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev)

if [[ "${NO_LAUNCH_AGENT:-0}" != "1" ]]; then
  if [[ -f "$PLIST_SRC" ]]; then
    info "Installing LaunchAgent at $PLIST_DST"
    mkdir -p "$(dirname "$PLIST_DST")"
    # Substitute $HOME and $INSTALL_DIR in plist template
    sed -e "s|{{INSTALL_DIR}}|$INSTALL_DIR|g" \
        -e "s|{{HOME}}|$HOME|g" \
        "$PLIST_SRC" > "$PLIST_DST"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    info "LaunchAgent loaded — cli-usage-bar will start at login."
  else
    warn "LaunchAgent plist template not found; skipping auto-start setup."
  fi
fi

BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/bin/usage-bar" "$BIN_DIR/usage-bar"
info "Installed control command: $BIN_DIR/usage-bar"
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
  warn "$BIN_DIR is not in PATH. Add this to your shell rc:"
  warn '    export PATH="$HOME/.local/bin:$PATH"'
fi

info "Launching now in the background…"
(cd "$INSTALL_DIR" && nohup .venv/bin/python -m cli_usage_bar >/tmp/cli-usage-bar.log 2>&1 &)

cat <<DONE

Done. Menu bar should show the 'AI' icon within a few seconds.

Control with:
  usage-bar start | stop | restart | status | logs | config | update | uninstall

Paths:
  config : $HOME/.config/cli-usage-bar/config.toml
  logs   : /tmp/cli-usage-bar.log
  repo   : $INSTALL_DIR
DONE
