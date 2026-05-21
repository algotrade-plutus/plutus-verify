"""Tests for the config loader: defaults + override merging."""
from pathlib import Path

import yaml

from plutus_verify.config import Config, load_config


def test_load_config_returns_defaults_when_no_path():
    cfg = load_config(None)
    assert isinstance(cfg, Config)
    assert cfg.llm.endpoint  # default endpoint set
    assert cfg.charts.match_threshold == 0.7
    assert cfg.execute.default_network == "none"


def test_load_config_merges_user_overrides(tmp_path: Path):
    overrides = {
        "llm": {"endpoint": "http://gemma:9000/v1", "model": "gemma-test"},
        "charts": {"match_threshold": 0.85},
        "tolerances": {
            "overrides": {
                "sharpe_ratio": {"kind": "absolute", "value": 0.1},
            }
        },
    }
    p = tmp_path / "plutus-verify.yaml"
    p.write_text(yaml.safe_dump(overrides))
    cfg = load_config(p)
    assert cfg.llm.endpoint == "http://gemma:9000/v1"
    assert cfg.llm.model == "gemma-test"
    assert cfg.charts.match_threshold == 0.85
    assert cfg.execute.default_network == "none"  # default preserved
    assert cfg.tolerances.overrides["sharpe_ratio"]["kind"] == "absolute"


def test_load_config_unknown_key_ignored_silently(tmp_path: Path):
    """Forward-compat: unknown top-level keys are ignored, not errors."""
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"future_feature": {"x": 1}}))
    cfg = load_config(p)
    assert cfg.llm.endpoint  # still loads with defaults
