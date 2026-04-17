from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "cli-usage-bar" / "config.toml"

PLAN_BUDGETS: dict[str, int] = {
    "pro": 19_000_000,
    "max5": 88_000_000,
    "max20": 220_000_000,
}


@dataclass
class GeneralConfig:
    refresh_interval_sec: int = 60
    show_title_percent: bool = True


@dataclass
class ClaudeCodeConfig:
    enabled: bool = True
    plan: str = "max20"
    custom_budget_tokens: int = 0

    def budget_tokens(self) -> int:
        if self.plan == "custom" and self.custom_budget_tokens > 0:
            return self.custom_budget_tokens
        return PLAN_BUDGETS.get(self.plan, PLAN_BUDGETS["max20"])


@dataclass
class CodexCliConfig:
    enabled: bool = True


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


def ensure_default_config(path: Path = CONFIG_PATH) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """[general]
refresh_interval_sec = 60
show_title_percent = true

[claude_code]
enabled = true
plan = "max20"            # pro | max5 | max20 | custom
custom_budget_tokens = 0  # only used when plan = "custom"

[codex_cli]
enabled = true
""",
        encoding="utf-8",
    )
    return path
