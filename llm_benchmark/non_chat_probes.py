"""Замеры embeddings, rerank (HTTP JSON), audio.transcriptions (OpenAI SDK)."""

from __future__ import annotations

# GRACE[M-LLM-BENCHMARK][INTEGRATION][BLOCK_NonChatProbes]
# CONTRACT: те же RunMetrics, что и chat; лог в app.http_access как upstream *.

import json
import logging
import time
import uuid
import wave
from io import BytesIO
from typing import Any

import httpx
from openai import APIError, OpenAI

from llm_benchmark.core import RunMetrics

_UPSTREAM = logging.getLogger("app.http_access")


def _approx_tokens(text: str) -> int:
    return max(1, int(len(text) / 4))


def _log_json(kind: str, batch_id: str, base_url: str, tag: str, payload: dict[str, Any]) -> None:
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        body = repr(payload)
    _UPSTREAM.info(
        "upstream %s batch=%s tag=%s base_url=%s body=%s",
        kind,
        batch_id,
        tag,
        base_url,
        body,
    )


def _failure(total_s: float, exc: BaseException, *, stream: bool = False) -> RunMetrics:
    status = None
    if isinstance(exc, APIError):
        sc = getattr(exc, "status_code", None)
        if sc is not None:
            status = int(sc)
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        status = exc.response.status_code
    return RunMetrics(
        ttft_s=None,
        total_s=total_s,
        prompt_tokens=None,
        completion_tokens=None,
        output_chars=0,
        gen_tps=None,
        e2e_tps=None,
        stream=stream,
        chunk_count=0,
        usage_from_api=False,
        success=False,
        error=str(exc),
        http_status=status,
    )


def silent_wav_bytes(*, duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    n = max(1, int(sample_rate * max(0.2, min(duration_s, 60.0))))
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def run_once_embedding(
    client: OpenAI,
    model: str,
    input_text: str,
    timeout: float,
    *,
    batch_id: str | None,
    tag: str,
) -> RunMetrics:
    req = {"model": model, "input": input_text, "timeout": timeout}
    if batch_id:
        _log_json(
            "embeddings.create",
            batch_id,
            str(client.base_url).rstrip("/"),
            tag,
            req,
        )
    t0 = time.perf_counter()
    try:
        resp = client.embeddings.create(**req)
    except Exception as e:  # noqa: BLE001
        return _failure(time.perf_counter() - t0, e, stream=False)
    total_s = time.perf_counter() - t0
    emb = resp.data[0].embedding if resp.data else []
    dims = len(emb)
    u = getattr(resp, "usage", None)
    pt = getattr(u, "prompt_tokens", None) if u else None
    total_t = getattr(u, "total_tokens", None) if u else None
    prompt_tokens = pt if pt is not None else total_t
    usage_from_api = prompt_tokens is not None
    if prompt_tokens is None and input_text:
        prompt_tokens = _approx_tokens(input_text)
        usage_from_api = False
    e2e_tps = (prompt_tokens / total_s) if (prompt_tokens and total_s > 0) else None
    return RunMetrics(
        ttft_s=None,
        total_s=total_s,
        prompt_tokens=prompt_tokens,
        completion_tokens=None,
        output_chars=dims,
        gen_tps=None,
        e2e_tps=e2e_tps,
        stream=False,
        chunk_count=0,
        usage_from_api=usage_from_api,
        success=True,
        error=None,
        http_status=None,
    )


def run_embedding_probe(
    base_url: str,
    api_key: str,
    model: str,
    input_text: str,
    *,
    timeout: float = 120.0,
    runs: int = 3,
    warmup: int = 0,
) -> tuple[list[RunMetrics], str]:
    client = OpenAI(api_key=api_key, base_url=base_url.rstrip("/"), max_retries=0)
    batch_id = str(uuid.uuid4())
    results: list[RunMetrics] = []
    wi = 0
    ri = 0

    def one() -> RunMetrics:
        nonlocal wi, ri
        tag = f"warmup{wi}" if wi < warmup else f"run{ri}"
        return run_once_embedding(client, model, input_text, timeout, batch_id=batch_id, tag=tag)

    for _ in range(warmup):
        one()
        wi += 1
    for _ in range(runs):
        results.append(one())
        ri += 1
    return results, batch_id


def run_once_rerank(
    base_url: str,
    api_key: str,
    model: str,
    query: str,
    documents: list[str],
    top_n: int,
    timeout: float,
    path_suffix: str,
    *,
    batch_id: str | None,
    tag: str,
) -> RunMetrics:
    base = base_url.rstrip("/")
    path = path_suffix.strip() or "/rerank"
    if not path.startswith("/"):
        path = "/" + path
    url = base + path
    safe_docs = list(documents)
    top_n = min(max(1, top_n), len(safe_docs)) if safe_docs else 1
    payload_for_log = {
        "model": model,
        "query": query[:500] + ("…" if len(query) > 500 else ""),
        "documents_count": len(safe_docs),
        "top_n": top_n,
    }
    if batch_id:
        _log_json("rerank.http", batch_id, base, tag, {"url": url, **payload_for_log})
    body: dict[str, Any] = {
        "model": model,
        "query": query,
        "documents": safe_docs,
        "top_n": top_n,
    }
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as hc:
            r = hc.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return _failure(time.perf_counter() - t0, e, stream=False)
    total_s = time.perf_counter() - t0
    n_docs = len(safe_docs)
    data = r.json()
    results = data.get("results")
    if results is None and isinstance(data.get("data"), list):
        results = data.get("data")
    n_res = len(results) if isinstance(results, list) else top_n
    e2e_tps = (n_docs / total_s) if total_s > 0 else None
    return RunMetrics(
        ttft_s=None,
        total_s=total_s,
        prompt_tokens=None,
        completion_tokens=None,
        output_chars=int(n_res),
        gen_tps=None,
        e2e_tps=e2e_tps,
        stream=False,
        chunk_count=n_docs,
        usage_from_api=False,
        success=True,
        error=None,
        http_status=r.status_code,
    )


def run_rerank_probe(
    base_url: str,
    api_key: str,
    model: str,
    *,
    query: str,
    documents: list[str],
    top_n: int = 5,
    rerank_path: str = "/rerank",
    timeout: float = 120.0,
    runs: int = 3,
    warmup: int = 0,
) -> tuple[list[RunMetrics], str]:
    batch_id = str(uuid.uuid4())
    results: list[RunMetrics] = []
    wi = 0
    ri = 0

    def one() -> RunMetrics:
        nonlocal wi, ri
        tag = f"warmup{wi}" if wi < warmup else f"run{ri}"
        return run_once_rerank(
            base_url,
            api_key,
            model,
            query,
            documents,
            top_n,
            timeout,
            rerank_path,
            batch_id=batch_id,
            tag=tag,
        )

    for _ in range(warmup):
        one()
        wi += 1
    for _ in range(runs):
        results.append(one())
        ri += 1
    return results, batch_id


def run_once_transcription(
    client: OpenAI,
    model: str,
    wav_bytes: bytes,
    timeout: float,
    language: str | None,
    *,
    batch_id: str | None,
    tag: str,
) -> RunMetrics:
    tup = ("probe.wav", wav_bytes, "audio/wav")
    if batch_id:
        _log_json(
            "audio.transcriptions",
            batch_id,
            str(client.base_url).rstrip("/"),
            tag,
            {"model": model, "file_bytes": len(wav_bytes), "language": language},
        )
    t0 = time.perf_counter()
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "file": tup,
            "timeout": timeout,
        }
        if language and str(language).strip():
            kwargs["language"] = str(language).strip()
        resp = client.audio.transcriptions.create(**kwargs)
    except Exception as e:  # noqa: BLE001
        return _failure(time.perf_counter() - t0, e, stream=False)
    total_s = time.perf_counter() - t0
    text = getattr(resp, "text", None) or ""
    out_chars = len(text)
    ct = _approx_tokens(text) if text else 0
    e2e_tps = (ct / total_s) if total_s > 0 else None
    return RunMetrics(
        ttft_s=None,
        total_s=total_s,
        prompt_tokens=None,
        completion_tokens=ct,
        output_chars=out_chars,
        gen_tps=None,
        e2e_tps=e2e_tps,
        stream=False,
        chunk_count=0,
        usage_from_api=False,
        success=True,
        error=None,
        http_status=None,
    )


def run_audio_transcription_probe(
    base_url: str,
    api_key: str,
    model: str,
    *,
    duration_s: float = 0.5,
    language: str | None = None,
    timeout: float = 120.0,
    runs: int = 3,
    warmup: int = 0,
) -> tuple[list[RunMetrics], str]:
    wav = silent_wav_bytes(duration_s=duration_s)
    client = OpenAI(api_key=api_key, base_url=base_url.rstrip("/"), max_retries=0)
    batch_id = str(uuid.uuid4())
    results: list[RunMetrics] = []
    wi = 0
    ri = 0

    def one() -> RunMetrics:
        nonlocal wi, ri
        tag = f"warmup{wi}" if wi < warmup else f"run{ri}"
        return run_once_transcription(
            client, model, wav, timeout, language, batch_id=batch_id, tag=tag
        )

    for _ in range(warmup):
        one()
        wi += 1
    for _ in range(runs):
        results.append(one())
        ri += 1
    return results, batch_id
