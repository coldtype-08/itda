"""Runtime configuration. Everything environment-specific comes from env vars or CLI flags."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

VISITOR_TYPES = ("foreign", "korean")
INTERESTS = ("family", "history", "kculture")


def _api_key() -> str:
    for name in ("ITDA_LLM_API_KEY", "NVIDIA_API_KEY", "NVIDIA_INFERENCE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    # inference.local (NemoClaw) and OpenShell providers inject the real credential
    # at the proxy, so a placeholder is enough inside a sandbox.
    return "unused"


@dataclass
class Config:
    task_file: Path
    input_dir: Path
    output_dir: Path
    visitor_type: str = "foreign"
    interests: list[str] = field(default_factory=lambda: ["history"])
    language: str | None = None          # None -> derived from visitor_type
    visit_date: str | None = None        # None -> inferred from task/input

    llm_base_url: str = field(default_factory=lambda: os.environ.get(
        "ITDA_LLM_BASE_URL", "https://integrate.api.nvidia.com/v1"))
    llm_api_key: str = field(default_factory=_api_key)
    # Small/fast model endpoint (e.g. Nemotron Nano NIM on the L40S). Empty -> same as llm_base_url.
    fast_base_url: str = field(default_factory=lambda: os.environ.get("ITDA_FAST_BASE_URL", ""))
    model_main: str = field(default_factory=lambda: os.environ.get(
        "ITDA_MODEL", "nvidia/nemotron-3-super-120b-a12b"))  # set to ...-ultra-550b-a55b for max quality
    model_fast: str = field(default_factory=lambda: os.environ.get(
        "ITDA_MODEL_FAST", os.environ.get("ITDA_MODEL", "nvidia/nemotron-3-super-120b-a12b")))
    llm_timeout: float = float(os.environ.get("ITDA_LLM_TIMEOUT", "180"))
    llm_extra_body: str = os.environ.get("ITDA_LLM_EXTRA_BODY", "")  # raw JSON merged into requests
    concurrency: int = int(os.environ.get("ITDA_CONCURRENCY", "8"))
    triage_mode: str = os.environ.get("ITDA_TRIAGE_MODE", "batch")  # batch | per_doc
    mock: bool = os.environ.get("ITDA_LLM_MOCK") == "1"

    def __post_init__(self) -> None:
        if self.visitor_type not in VISITOR_TYPES:
            raise ValueError(f"visitor_type must be one of {VISITOR_TYPES}")
        bad = [i for i in self.interests if i not in INTERESTS]
        if bad:
            raise ValueError(f"unknown interests {bad}; choose from {INTERESTS}")
        if self.language is None:
            self.language = "en" if self.visitor_type == "foreign" else "ko"
