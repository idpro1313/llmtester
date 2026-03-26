from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)


class GlobalSettings(Base):
    """Одна строка настроек приложения (id=1)."""

    __tablename__ = "global_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    benchmark_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    probe_interval_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    default_warmup: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    default_timeout: Mapped[float] = mapped_column(Float, default=120.0, nullable=False)


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    """Короткий код: cloud_ru, yandex, mws, custom."""
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    targets: Mapped[list["MonitoredTarget"]] = relationship(
        "MonitoredTarget", back_populates="provider", cascade="all, delete-orphan"
    )


class MonitoredTarget(Base):
    __tablename__ = "monitored_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=512, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    use_stream: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    runs_per_probe: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    warmup_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    provider: Mapped["Provider"] = relationship("Provider", back_populates="targets")
    measurements: Mapped[list["Measurement"]] = relationship(
        "Measurement", back_populates="target", cascade="all, delete-orphan"
    )


class Measurement(Base):
    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("monitored_targets.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ttft_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_s: Mapped[float] = mapped_column(Float, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gen_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    e2e_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    stream: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_from_api: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    inter_chunk_gap_mean_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    inter_chunk_gap_max_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    target: Mapped["MonitoredTarget"] = relationship("MonitoredTarget", back_populates="measurements")
