from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "cli-usage-bar" / "config.toml"

# Empirical 5-hour token budgets derived from observed dashboard percentages.
# Anthropic does not publish these numbers; these are starting estimates that
# the user can override with the "calibrate" flow (see README).
PLAN_BUDGETS: dict[str, int] = {
    "pro": 1_500_000,
    "max5": 7_500_000,
    "max20": 30_000_000,
}


@dataclass
class GeneralConfig:
    refresh_interval_sec: int = 60
    show_title_percent: bool = True


@dataclass
class ClaudeCodeConfig:
    enabled: bool = True
    plan: str = "max5"
    custom_budget_tokens: int = 0
    # Weekly budget multiplier relative to the 5-hour block budget. The
    # empirical Max (5x) ratio — ~72M tokens used / 7d ≈ 6% dashboard — points
    # to ~1.2B weekly vs ~7.5M per 5h block, i.e. a ~150x multiplier.
    weekly_budget_multiplier: float = 150.0
    title_label: str = "C"
    title_show_primary: bool = True
    title_show_secondary: bool = False
    title_show_reset: bool = False
    # Threshold alerts. 0 = disabled. Fires once per block when the
    # percentage first crosses the threshold; re-arms at the next reset.
    alert_primary_percent: int = 0
    alert_secondary_percent: int = 0
    # Human-readable plan name shown in the menu ("Max (5x)", "Pro", ...).
    # Empty → derived from ``plan`` below. Useful after Calibrate which
    # switches ``plan`` to "custom" but leaves the subscription unchanged.
    plan_label: str = ""

    def plan_display(self) -> str:
        if self.plan_label:
            return self.plan_label
        return {
            "pro": "Pro",
            "max5": "Max (5x)",
            "max20": "Max (20x)",
            "custom": "Custom",
        }.get(self.plan, self.plan)

    def budget_tokens(self) -> int:
        if self.plan == "custom" and self.custom_budget_tokens > 0:
            return self.custom_budget_tokens
        return PLAN_BUDGETS.get(self.plan, PLAN_BUDGETS["max5"])

    def weekly_budget_tokens(self) -> int:
        return int(self.budget_tokens() * self.weekly_budget_multiplier)


@dataclass
class CodexCliConfig:
    enabled: bool = True
    title_label: str = "X"
    title_show_primary: bool = True
    title_show_secondary: bool = False
    title_show_reset: bool = False
    alert_primary_percent: int = 0
    alert_secondary_percent: int = 0


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    claude_code: ClaudeCodeConfig = field(default_factory=ClaudeCodeConfig)
    codex_cli: CodexCliConfig = field(default_factory=CodexCliConfig)


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    general = GeneralConfig(**raw.get("general", {}))
    claude = ClaudeCodeConfig(**raw.get("claude_code", {}))
    codex = CodexCliConfig(**raw.get("codex_cli", {}))
    return Config(general=general, claude_code=claude, codex_cli=codex)


DEFAULT_CONFIG_TEXT = """[general]
refresh_interval_sec = 60
show_title_percent = true

[claude_code]
enabled = true
plan = "max5"                    # pro | max5 | max20 | custom
custom_budget_tokens = 0         # used only when plan = "custom"
weekly_budget_multiplier = 150.0 # weekly pool size relative to the 5h block
title_label = "C"                # prefix shown in the menu bar title
title_show_primary = true        # include the 5h percent in the title
title_show_secondary = false     # include the weekly percent in the title
title_show_reset = false         # append remaining time next to each percent
alert_primary_percent = 0        # notify when 5h % crosses this (0 = off)
alert_secondary_percent = 0      # notify when weekly % crosses this (0 = off)
plan_label = ""                  # e.g. "Max (5x)" — shown in menu; "" = auto

[codex_cli]
enabled = true
title_label = "X"                # prefix shown in the menu bar title
title_show_primary = true        # include the 5h percent in the title
title_show_secondary = false     # include the weekly percent in the title
title_show_reset = false         # append remaining time next to each percent
alert_primary_percent = 0        # notify when 5h % crosses this (0 = off)
alert_secondary_percent = 0      # notify when weekly % crosses this (0 = off)
"""


def ensure_default_config(path: Path = CONFIG_PATH) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return path


def calibrate_from_dashboard(
    tokens_used: int,
    dashboard_percent: float,
    path: Path = CONFIG_PATH,
) -> int:
    """Derive a ``custom_budget_tokens`` value from an observed dashboard pair.

    Writes ``plan = "custom"`` and the computed budget into the config file.
    Returns the computed budget.
    """
    if dashboard_percent <= 0:
        raise ValueError("dashboard_percent must be > 0")
    budget = int(round(tokens_used / (dashboard_percent / 100.0)))

    if not path.exists():
        ensure_default_config(path)
    raw = path.read_text(encoding="utf-8")
    raw = _set_toml_value(raw, "claude_code", "plan", '"custom"')
    raw = _set_toml_value(raw, "claude_code", "custom_budget_tokens", str(budget))
    path.write_text(raw, encoding="utf-8")
    return budget


def _set_toml_value(text: str, section: str, key: str, value: str) -> str:
    """Naive single-value TOML setter for known keys. Preserves surrounding lines."""
    lines = text.splitlines(keepends=True)
    in_section = False
    written = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not written:
                out.append(f"{key} = {value}\n")
                written = True
            in_section = stripped == f"[{section}]"
        elif in_section and stripped.startswith(f"{key}") and "=" in stripped:
            prefix = line[: len(line) - len(line.lstrip())]
            # Preserve inline comment if present
            comment = ""
            if "#" in line:
                comment = "  " + line[line.index("#") :].rstrip()
            out.append(f"{prefix}{key} = {value}{comment}\n")
            written = True
            continue
        out.append(line)
    if in_section and not written:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(f"{key} = {value}\n")
    return "".join(out)
