"""Ядро замеров OpenAI-compatible Chat Completions."""

# GRACE[M-LLM-BENCHMARK][PACKAGE][BLOCK_PublicExports]
# CONTRACT: реэкспорт DEFAULT_PROMPT, run_probe, run_once_*, RunMetrics из core.

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
