"""Чтение хвоста файла лога HTTP-запросов."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.local_secrets import monitor_data_dir


@dataclass
class LogFileInfo:
    path: Path
    exists: bool
    size_bytes: int


def log_file_path() -> Path:
    return monitor_data_dir() / "requests.log"


def list_log_files() -> list[LogFileInfo]:
    """Текущий и ротированные куски (requests.log, requests.log.1, …)."""
    base = monitor_data_dir()
    names = ["requests.log"] + [f"requests.log.{i}" for i in range(1, 6)]
    out: list[LogFileInfo] = []
    for n in names:
        p = base / n
        if p.is_file():
            out.append(LogFileInfo(path=p, exists=True, size_bytes=p.stat().st_size))
    return out


def read_requests_log_tail(max_lines: int, max_bytes: int = 512_000) -> tuple[str, list[LogFileInfo]]:
    """
    Возвращает (текст последних max_lines строк из текущего requests.log, инфо о файлах).
    Читает с конца файла не более max_bytes байт для экономии памяти.
    """
    path = log_file_path()
    files = list_log_files()
    if not path.is_file():
        return "", files

    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return "", files
            read_size = min(size, max_bytes)
            f.seek(size - read_size)
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail), files
    except OSError:
        return "(не удалось прочитать файл лога)", files
