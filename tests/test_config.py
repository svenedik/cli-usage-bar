from __future__ import annotations

import logging

from cli_usage_bar.config import load_config


def test_load_config_ignores_unknown_keys(tmp_path, caplog):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[general]
refresh_interval_sec = 30
unknown = true

[claude_code]
plan_label = "Max (5x)"
extra = "ignored"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="cli_usage_bar.config"):
        config = load_config(path)

    assert config.general.refresh_interval_sec == 30
    assert config.claude_code.plan_label == "Max (5x)"
    assert "unknown config keys in [general]" in caplog.text
    assert "unknown config keys in [claude_code]" in caplog.text


def test_load_config_reads_alert_thresholds_from_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[claude_code]
alert_primary_percent = 80
alert_secondary_percent = 85

[codex_cli]
alert_primary_percent = 70
alert_secondary_percent = 0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.claude_code.alert_primary_percent == 80
    assert config.claude_code.alert_secondary_percent == 85
    assert config.codex_cli.alert_primary_percent == 70
    assert config.codex_cli.alert_secondary_percent == 0


def test_default_alert_thresholds_are_90_and_95(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[claude_code]\n", encoding="utf-8")

    config = load_config(path)

    assert config.claude_code.alert_primary_percent == 90
    assert config.claude_code.alert_secondary_percent == 95
    assert config.codex_cli.alert_primary_percent == 90
    assert config.codex_cli.alert_secondary_percent == 95
