"""Ядро замеров OpenAI-compatible Chat Completions."""

from llm_benchmark.core import (
    DEFAULT_PROMPT,
    RunMetrics,
    run_once_blocking,
    run_once_stream,
    run_probe,
)

__all__ = [
    "DEFAULT_PROMPT",
    "RunMetrics",
    "run_once_blocking",
    "run_once_stream",
    "run_probe",
]
