#!/usr/bin/env python3
"""
CLI: бенчмарк скорости LLM через OpenAI-compatible Chat Completions.
Логика замеров в пакете llm_benchmark.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from llm_benchmark.provider_headers import x_api_key_headers

from llm_benchmark.core import (
    DEFAULT_PROMPT,
    RunMetrics,
    run_once_blocking,
    run_once_stream,
)
from openai import APIError as OpenAIAPIError


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def workspace_dir() -> Path:
    return repo_root() / "workspace"


def resolve_prompt_path(prompt_file: str) -> Path:
    p = Path(prompt_file)
    if p.is_file():
        return p.resolve()
    wp = workspace_dir() / prompt_file
    if wp.is_file():
        return wp.resolve()
    raise SystemExit(f"Файл с промптом не найден: {prompt_file}")


def load_prompt(text: Optional[str], prompt_path: Optional[Path]) -> tuple[str, Optional[str]]:
    if prompt_path is not None:
        return prompt_path.read_text(encoding="utf-8"), str(prompt_path)
    return text or DEFAULT_PROMPT, None


def build_report_dict(
    runs: list[RunMetrics],
    model: str,
    base_url: str,
    prompt_source: Optional[str],
) -> dict[str, Any]:
    dicts = [m.to_dict() for m in runs]

    def stat_vals(key: str) -> Optional[list[float]]:
        vals = []
        for r in dicts:
            v = r.get(key)
            if v is not None:
                vals.append(float(v))
        return vals or None

    agg: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "runs": len(runs),
        "success_rate": sum(1 for r in runs if r.success) / len(runs) if runs else 0.0,
        "total_s": {
            "mean": statistics.mean(stat_vals("total_s") or [0]),
            "min": min(stat_vals("total_s") or [0]),
            "max": max(stat_vals("total_s") or [0]),
        },
    }
    g = stat_vals("gen_tps")
    if g:
        agg["gen_tokens_per_s"] = {"mean": statistics.mean(g), "min": min(g), "max": max(g)}
    e = stat_vals("e2e_tps")
    if e:
        agg["e2e_tokens_per_s"] = {"mean": statistics.mean(e), "min": min(e), "max": max(e)}
    t = stat_vals("ttft_s")
    if t:
        agg["ttft_s"] = {"mean": statistics.mean(t), "min": min(t), "max": max(t), "unit": "seconds"}
    ch = stat_vals("chunk_count")
    if ch:
        agg["chunk_count"] = {"mean": statistics.mean(ch), "min": min(ch), "max": max(ch)}
    ig = stat_vals("inter_chunk_gap_mean_s")
    if ig:
        agg["inter_chunk_gap_mean_s"] = {"mean": statistics.mean(ig), "min": min(ig), "max": max(ig)}

    meta = {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "prompt_file": prompt_source,
    }
    return {"aggregate": agg, "per_run": dicts, "meta": meta}


def resolve_output_path(output_arg: Optional[str]) -> Path:
    if output_arg is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return workspace_dir() / f"llm-benchmark_{stamp}.json"
    p = Path(output_arg)
    if not p.is_absolute() and str(p.parent) in (".", ""):
        out = workspace_dir() / p.name
    else:
        out = p
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def print_human_report(runs: list[RunMetrics], model: str, base_url: str) -> None:
    report = build_report_dict(runs, model, base_url, None)
    dicts = report["per_run"]

    def stat_vals(key: str) -> Optional[list[float]]:
        vals = []
        for r in dicts:
            v = r.get(key)
            if v is not None:
                vals.append(float(v))
        return vals or None

    t = stat_vals("ttft_s")
    g = stat_vals("gen_tps")
    e = stat_vals("e2e_tps")

    print(f"Модель: {model}")
    print(f"Base URL: {base_url}")
    print(f"Прогонов: {len(runs)}  (стриминг: {runs[0].stream})")
    print(f"Успешных: {sum(1 for r in runs if r.success)}/{len(runs)}")
    print()
    ts = stat_vals("total_s") or [0]
    print(f"Общее время ответа (с): mean={statistics.mean(ts):.3f}  min={min(ts):.3f}  max={max(ts):.3f}")
    if t:
        print(
            f"TTFT — до первого токена (с): mean={statistics.mean(t):.3f}  "
            f"min={min(t):.3f}  max={max(t):.3f}"
        )
    if g:
        print(
            f"Скорость генерации (токенов/с, без простоя до первого токена): "
            f"mean={statistics.mean(g):.1f}  min={min(g):.1f}  max={max(g):.1f}"
        )
    if e:
        print(
            f"Скорость end-to-end (токенов/с): "
            f"mean={statistics.mean(e):.1f}  min={min(e):.1f}  max={max(e):.1f}"
        )
    for r in runs:
        if not r.success:
            print(f"Ошибка: {r.error}")
    print()
    print("Подсказка: если usage_from_api=false, completion-токены оценены (~4 симв/токен).")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Замер скорости LLM (OpenAI-compatible API): TTFT, время ответа, токены/с.",
    )
    p.add_argument(
        "prompt_path",
        nargs="?",
        default=None,
        metavar="PROMPT_FILE",
        help="Файл с текстом промпта (путь или имя в workspace/). Имеет приоритет над --prompt-file",
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        help="Базовый URL API (по умолчанию OPENAI_BASE_URL или api.openai.com)",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY", ""),
        help="Ключ API (или переменная OPENAI_API_KEY)",
    )
    p.add_argument("--model", required=True, help="Имя модели на сервере")
    p.add_argument("--prompt", default=None, help="Текст промпта (иначе встроенный тестовый)")
    p.add_argument(
        "--prompt-file",
        dest="prompt_file_opt",
        default=None,
        help="Файл с промптом (путь или имя в workspace/). Либо передайте тот же файл позиционным аргументом",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        dest="output",
        metavar="PATH",
        help="Куда записать JSON-отчёт. Только имя файла -> workspace/<имя>. "
        "По умолчанию: workspace/llm-benchmark_ГГГГММДД_ЧЧММСС.json",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="Не записывать отчёт в файл (только вывод в консоль)",
    )
    p.add_argument("--max-tokens", type=int, default=512, help="Лимит new tokens")
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--timeout", type=float, default=120.0, help="Таймаут HTTP (с)")
    p.add_argument("--runs", type=int, default=3, help="Число замеров подряд")
    p.add_argument("--warmup", type=int, default=0, help="Прогревочные запросы (не в отчёт)")
    p.add_argument(
        "--no-stream",
        action="store_true",
        help="Обычный (не стриминговый) запрос — без TTFT и gen_tps",
    )
    p.add_argument("--json", action="store_true", dest="json_out", help="Вывод только JSON")
    return p.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    if not args.api_key:
        print("Нужен --api-key или переменная окружения OPENAI_API_KEY.", file=sys.stderr)
        sys.exit(2)

    prompt_file_str = args.prompt_path or args.prompt_file_opt
    prompt_path: Optional[Path] = resolve_prompt_path(prompt_file_str) if prompt_file_str else None
    prompt, prompt_source = load_prompt(args.prompt, prompt_path)

    client = OpenAI(
        base_url=args.base_url.rstrip("/"),
        api_key=args.api_key,
        default_headers=x_api_key_headers(args.api_key),
    )

    stream_include_usage = True
    measured: list[RunMetrics] = []

    def do_warmup() -> None:
        nonlocal stream_include_usage
        for _ in range(args.warmup):
            if args.no_stream:
                run_once_blocking(
                    client,
                    args.model,
                    prompt,
                    args.max_tokens,
                    args.temperature,
                    args.timeout,
                )
            else:
                try:
                    run_once_stream(
                        client,
                        args.model,
                        prompt,
                        args.max_tokens,
                        args.temperature,
                        args.timeout,
                        include_usage=stream_include_usage,
                    )
                except OpenAIAPIError:
                    if stream_include_usage:
                        stream_include_usage = False
                        run_once_stream(
                            client,
                            args.model,
                            prompt,
                            args.max_tokens,
                            args.temperature,
                            args.timeout,
                            include_usage=False,
                        )
                    else:
                        raise

    do_warmup()

    for i in range(args.runs):
        try:
            if args.no_stream:
                m = run_once_blocking(
                    client,
                    args.model,
                    prompt,
                    args.max_tokens,
                    args.temperature,
                    args.timeout,
                )
            else:
                try:
                    m = run_once_stream(
                        client,
                        args.model,
                        prompt,
                        args.max_tokens,
                        args.temperature,
                        args.timeout,
                        include_usage=stream_include_usage,
                    )
                except OpenAIAPIError:
                    if stream_include_usage:
                        stream_include_usage = False
                        m = run_once_stream(
                            client,
                            args.model,
                            prompt,
                            args.max_tokens,
                            args.temperature,
                            args.timeout,
                            include_usage=False,
                        )
                    else:
                        raise
        except OpenAIAPIError as e:
            print(f"Ошибка API: {e}", file=sys.stderr)
            sys.exit(1)
        measured.append(m)
        if not args.json_out:
            print(f"Прогон {i + 1}/{args.runs}: total={m.total_s:.3f}s", flush=True)

    report = build_report_dict(measured, args.model, args.base_url, prompt_source)
    out_path: Optional[Path] = None
    if not args.no_save:
        out_path = resolve_output_path(args.output)
        report["meta"]["report_path"] = str(out_path.resolve())
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human_report(measured, args.model, args.base_url)
        if out_path is not None:
            print(f"Отчёт JSON: {out_path.resolve()}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
