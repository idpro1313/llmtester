"""Типы замеров цели мониторинга (OpenAI-compatible и смежные API)."""

from __future__ import annotations

# GRACE[M-SVC-PROBE][DOMAIN][BLOCK_ProbeKinds]
# CONTRACT: нормализация probe_kind; подписи для UI.

PROBE_KIND_CHAT = "chat"
PROBE_KIND_EMBEDDING = "embedding"
PROBE_KIND_RERANK = "rerank"
PROBE_KIND_AUDIO_TRANSCRIPTION = "audio_transcription"

PROBE_KINDS: tuple[str, ...] = (
    PROBE_KIND_CHAT,
    PROBE_KIND_EMBEDDING,
    PROBE_KIND_RERANK,
    PROBE_KIND_AUDIO_TRANSCRIPTION,
)

PROBE_KIND_LABELS_RU: dict[str, str] = {
    PROBE_KIND_CHAT: "Чат (chat completions)",
    PROBE_KIND_EMBEDDING: "Эмбеддинги (embeddings)",
    PROBE_KIND_RERANK: "Реранк (rerank)",
    PROBE_KIND_AUDIO_TRANSCRIPTION: "Аудио → текст (transcription)",
}


def normalize_probe_kind(raw: str | None) -> str:
    k = (raw or PROBE_KIND_CHAT).strip().lower()
    return k if k in PROBE_KINDS else PROBE_KIND_CHAT


def probe_kind_label_ru(kind: str) -> str:
    return PROBE_KIND_LABELS_RU.get(kind, kind)


def probe_kind_choices() -> list[tuple[str, str]]:
    return [(k, PROBE_KIND_LABELS_RU[k]) for k in PROBE_KINDS]
