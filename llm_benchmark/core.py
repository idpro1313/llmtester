"""Замер скорости LLM через OpenAI-compatible API (стриминг / блокирующий режим)."""

from __future__ import annotations

# GRACE[M-LLM-BENCHMARK][INTEGRATION][BLOCK_RunProbe]
# CONTRACT: run_probe / chat.completions; max_retries=0; лог тела запроса в app.http_access.

import json
import logging
import statistics
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Optional

from openai import APIError, OpenAI

# Тот же логгер, что входящие запросы (requests.log); без хендлеров — сообщения игнорируются.
_UPSTREAM_ACCESS = logging.getLogger("app.http_access")


def _log_chat_completions_body(
    *,
    batch_id: str,
    base_url: str,
    tag: str,
    request_kwargs: dict[str, Any],
) -> None:
    """Пишет в access-лог JSON тела запроса к chat/completions (без API-ключа — он только в заголовках)."""
    try:
        body = json.dumps(request_kwargs, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        body = repr(request_kwargs)
    _UPSTREAM_ACCESS.info(
        "upstream chat.completions batch=%s tag=%s base_url=%s body=%s",
        batch_id,
        tag,
        base_url,
        body,
    )

DEFAULT_PROMPT = (
    "Кратко перечисли 5 причин, почему измеряют latency и throughput LLM в продакшене. "
    "Ответ структурируй маркированным списком, каждый пункт 1–2 предложения."
)


@dataclass
class RunMetrics:
    ttft_s: Optional[float]
    total_s: float
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    output_chars: int
    gen_tps: Optional[float]
    e2e_tps: Optional[float]
    stream: bool
    chunk_count: int = 0
    """Число стриминговых чанков с ненулевым текстом."""
    usage_from_api: bool = False
    """True, если prompt/completion tokens пришли из usage (не оценка по длине)."""
    inter_chunk_gap_mean_s: Optional[float] = None
    inter_chunk_gap_max_s: Optional[float] = None
    """Интервалы между чанками с контентом (после первого токена)."""
    success: bool = True
    error: Optional[str] = None
    http_status: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _approx_tokens_from_text(text: str) -> int:
    return max(1, int(len(text) / 4))


def _stream_delta_text(delta: Any) -> str:
    if delta is None:
        return ""
    parts: list[str] = []

    def take_str(val: Any) -> None:
        if isinstance(val, str) and val:
            parts.append(val)

    if isinstance(delta, dict):
        for key in ("content", "reasoning_content", "refusal"):
            take_str(delta.get(key))
        c = delta.get("content")
        if isinstance(c, list):
            for item in c:
                if isinstance(item, dict) and item.get("type") == "text":
                    take_str(item.get("text"))
        return "".join(parts)

    for attr in ("content", "reasoning_content", "refusal"):
        take_str(getattr(delta, attr, None))
    c = getattr(delta, "content", None)
    if isinstance(c, list):
        for item in c:
            if isinstance(item, dict) and item.get("type") == "text":
                take_str(item.get("text"))

    if not parts and hasattr(delta, "model_dump"):
        dumped = delta.model_dump(exclude_none=True)
        if isinstance(dumped, dict):
            for key in ("content", "reasoning_content", "refusal"):
                take_str(dumped.get(key))
    return "".join(parts)


def _gaps_stats(gaps: list[float]) -> tuple[Optional[float], Optional[float]]:
    if not gaps:
        return None, None
    return statistics.mean(gaps), max(gaps)


def run_once_stream(
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float,
    include_usage: bool,
    *,
    probe_batch_id: str | None = None,
    probe_tag: str = "stream",
) -> RunMetrics:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "timeout": timeout,
    }
    if include_usage:
        kwargs["stream_options"] = {"include_usage": True}

    if probe_batch_id:
        _log_chat_completions_body(
            batch_id=probe_batch_id,
            base_url=str(client.base_url).rstrip("/"),
            tag=probe_tag,
            request_kwargs=kwargs,
        )

    stream = client.chat.completions.create(**kwargs)
    t0 = time.perf_counter()
    ttft: Optional[float] = None
    parts: list[str] = []
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    usage_from_api = False
    chunk_count = 0
    gaps: list[float] = []
    last_content_t: Optional[float] = None

    for chunk in stream:
        if chunk.usage:
            prompt_tokens = chunk.usage.prompt_tokens
            completion_tokens = chunk.usage.completion_tokens
            usage_from_api = completion_tokens is not None or prompt_tokens is not None
        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            continue
        delta = choice.delta
        if delta is None:
            continue
        piece = _stream_delta_text(delta)
        if not piece:
            continue
        now = time.perf_counter()
        chunk_count += 1
        if ttft is None:
            ttft = now - t0
        elif last_content_t is not None:
            gaps.append(now - last_content_t)
        last_content_t = now
        parts.append(piece)

    total_s = time.perf_counter() - t0
    text = "".join(parts)
    out_chars = len(text)

    if completion_tokens is None:
        completion_tokens = _approx_tokens_from_text(text)
        usage_from_api = False
    else:
        usage_from_api = True

    gen_s = (total_s - ttft) if ttft is not None and ttft > 0 else total_s
    gen_tps = (completion_tokens / gen_s) if gen_s > 0 else None
    e2e_tps = (completion_tokens / total_s) if total_s > 0 else None
    gap_mean, gap_max = _gaps_stats(gaps)

    return RunMetrics(
        ttft_s=ttft,
        total_s=total_s,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        output_chars=out_chars,
        gen_tps=gen_tps,
        e2e_tps=e2e_tps,
        stream=True,
        chunk_count=chunk_count,
        usage_from_api=usage_from_api,
        inter_chunk_gap_mean_s=gap_mean,
        inter_chunk_gap_max_s=gap_max,
        success=True,
        error=None,
        http_status=None,
    )


def run_once_blocking(
    client: OpenAI,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float,
    *,
    probe_batch_id: str | None = None,
    probe_tag: str = "blocking",
) -> RunMetrics:
    req: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
        "stream": False,
    }
    if probe_batch_id:
        _log_chat_completions_body(
            batch_id=probe_batch_id,
            base_url=str(client.base_url).rstrip("/"),
            tag=probe_tag,
            request_kwargs=req,
        )
    t0 = time.perf_counter()
    resp = client.chat.completions.create(**req)
    total_s = time.perf_counter() - t0
    text = (resp.choices[0].message.content or "") if resp.choices else ""
    out_chars = len(text)
    u = resp.usage
    prompt_tokens = u.prompt_tokens if u else None
    completion_tokens = u.completion_tokens if u else None
    usage_from_api = completion_tokens is not None
    if completion_tokens is None:
        completion_tokens = _approx_tokens_from_text(text)
        usage_from_api = False

    e2e_tps = (completion_tokens / total_s) if total_s > 0 else None

    return RunMetrics(
        ttft_s=None,
        total_s=total_s,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        output_chars=out_chars,
        gen_tps=None,
        e2e_tps=e2e_tps,
        stream=False,
        chunk_count=0,
        usage_from_api=usage_from_api,
        success=True,
        error=None,
        http_status=None,
    )


def _failure_metric_stream(t0: float, exc: BaseException) -> RunMetrics:
    total_s = time.perf_counter() - t0
    status = None
    if isinstance(exc, APIError):
        sc = getattr(exc, "status_code", None)
        if sc is not None:
            status = int(sc)
    return RunMetrics(
        ttft_s=None,
        total_s=total_s,
        prompt_tokens=None,
        completion_tokens=None,
        output_chars=0,
        gen_tps=None,
        e2e_tps=None,
        stream=True,
        chunk_count=0,
        usage_from_api=False,
        success=False,
        error=str(exc),
        http_status=status,
    )


def _failure_metric_blocking(t0: float, exc: BaseException) -> RunMetrics:
    total_s = time.perf_counter() - t0
    status = None
    if isinstance(exc, APIError):
        sc = getattr(exc, "status_code", None)
        if sc is not None:
            status = int(sc)
    return RunMetrics(
        ttft_s=None,
        total_s=total_s,
        prompt_tokens=None,
        completion_tokens=None,
        output_chars=0,
        gen_tps=None,
        e2e_tps=None,
        stream=False,
        chunk_count=0,
        usage_from_api=False,
        success=False,
        error=str(exc),
        http_status=status,
    )


def run_probe(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    max_tokens: int = 512,
    temperature: float = 0.2,
    timeout: float = 120.0,
    stream: bool = True,
    runs: int = 3,
    warmup: int = 0,
) -> tuple[list[RunMetrics], str]:
    """
    Прогрев и серия замеров. Возвращает (список метрик, batch_id).
    Ошибки API превращаются в RunMetrics с success=False (цикл не прерывается).
    """
    client = OpenAI(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        max_retries=0,
    )
    include_usage = True
    batch_id = str(uuid.uuid4())
    results: list[RunMetrics] = []
    _warm_i = 0
    _run_i = 0

    def one_stream() -> RunMetrics:
        nonlocal include_usage, _warm_i, _run_i
        t0 = time.perf_counter()
        tag = f"warmup{_warm_i}" if _warm_i < warmup else f"run{_run_i}"
        try:
            return run_once_stream(
                client,
                model,
                prompt,
                max_tokens,
                temperature,
                timeout,
                include_usage,
                probe_batch_id=batch_id,
                probe_tag=tag,
            )
        except APIError as e:
            if include_usage:
                include_usage = False
                try:
                    return run_once_stream(
                        client,
                        model,
                        prompt,
                        max_tokens,
                        temperature,
                        timeout,
                        False,
                        probe_batch_id=batch_id,
                        probe_tag=f"{tag}_no_usage_opt",
                    )
                except Exception as ex:  # noqa: BLE001
                    return _failure_metric_stream(t0, ex)
            return _failure_metric_stream(t0, e)
        except Exception as e:  # noqa: BLE001
            return _failure_metric_stream(t0, e)

    def one_block() -> RunMetrics:
        nonlocal _warm_i, _run_i
        t0 = time.perf_counter()
        tag = f"warmup{_warm_i}" if _warm_i < warmup else f"run{_run_i}"
        try:
            return run_once_blocking(
                client,
                model,
                prompt,
                max_tokens,
                temperature,
                timeout,
                probe_batch_id=batch_id,
                probe_tag=tag,
            )
        except Exception as e:  # noqa: BLE001
            return _failure_metric_blocking(t0, e)

    one = one_stream if stream else one_block

    for _ in range(warmup):
        one()
        _warm_i += 1

    for _ in range(runs):
        results.append(one())
        _run_i += 1

    return results, batch_id
