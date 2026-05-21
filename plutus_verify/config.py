"""Configuration loader: defaults + YAML overrides."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class LLMConfig:
    endpoint: str = "http://localhost:11434/v1"  # Ollama default
    model: str = "gemma4:26b"
    vision_model: str = "gemma4:26b"
    temperature: float = 0.1  # §5: 0.1 stable; 0 plus no repeat penalty can loop
    max_retries: int = 3       # §3
    timeout_seconds: int = 90  # content-idle timer for RETRIES; §2
    first_attempt_timeout_seconds: int = 180  # cold prompt eval headroom; §8
    num_ctx: int = 16384       # §4
    prewarm: bool = True       # §8
    think: bool = True         # Gemma 4 CoT — better JSON when enabled; thinking tokens still reset the idle timer but don't flow to the output


@dataclass
class ToleranceConfig:
    ratio_relative: float = 0.05
    percentage_absolute: float = 1.0
    pct_point_absolute: float = 0.02
    integer_absolute: float = 0.0
    default_relative: float = 0.10
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class ChartsConfig:
    enabled: bool = True
    rasterize_dpi: int = 144
    match_threshold: float = 0.7
    treat_partial_as_pass: bool = False


@dataclass
class ExecuteConfig:
    default_timeout_seconds: int = 1800
    default_network: str = "none"
    data_step_network: str = "bridge"
    memory_limit: str = "8g"
    cpu_limit: str = "4"


@dataclass
class Repo2DockerConfig:
    image_prefix: str = "plutus-run"
    cache: bool = True
    extra_args: list[str] = field(default_factory=list)


@dataclass
class CompareConfig:
    llm_fallback: bool = True   # try LLM-eyeballing when deterministic locate fails


@dataclass
class OverridesConfig:
    """Reviewer overrides applied AFTER Gemma's extracted plan is parsed."""
    artifact_only_steps: list[str] = field(default_factory=list)


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    tolerances: ToleranceConfig = field(default_factory=ToleranceConfig)
    charts: ChartsConfig = field(default_factory=ChartsConfig)
    compare: CompareConfig = field(default_factory=CompareConfig)
    execute: ExecuteConfig = field(default_factory=ExecuteConfig)
    repo2docker: Repo2DockerConfig = field(default_factory=Repo2DockerConfig)
    overrides: OverridesConfig = field(default_factory=OverridesConfig)


def _apply_overrides(target, overrides: dict[str, Any]) -> None:
    """Set known fields on a dataclass instance; ignore unknown keys."""
    for k, v in overrides.items():
        if hasattr(target, k):
            current = getattr(target, k)
            if isinstance(v, dict) and hasattr(current, "__dataclass_fields__"):
                _apply_overrides(current, v)
            else:
                setattr(target, k, v)


def load_config(path: Optional[Path]) -> Config:
    cfg = Config()
    if path is None:
        return cfg
    path = Path(path)
    if not path.exists():
        return cfg
    raw = yaml.safe_load(path.read_text()) or {}
    _apply_overrides(cfg, raw)
    return cfg
