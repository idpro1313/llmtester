"""Добавление колонок к существующим таблицам (без Alembic)."""

from __future__ import annotations

# GRACE[M-BOOT][PERSIST][BLOCK_SchemaMigrate]
# CONTRACT: additive ALTER для probe_kind / task_config_json на целях и замерах.

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrate_engine(engine: Engine) -> None:
    insp = inspect(engine)
    try:
        mt_cols = {c["name"] for c in insp.get_columns("monitored_targets")}
        ms_cols = {c["name"] for c in insp.get_columns("measurements")}
    except Exception:
        return

    stmts: list[str] = []
    if "probe_kind" not in mt_cols:
        stmts.append(
            "ALTER TABLE monitored_targets ADD COLUMN probe_kind VARCHAR(32) DEFAULT 'chat'"
        )
    if "task_config_json" not in mt_cols:
        stmts.append(
            "ALTER TABLE monitored_targets ADD COLUMN task_config_json TEXT DEFAULT '{}'"
        )
    if "probe_kind" not in ms_cols:
        stmts.append("ALTER TABLE measurements ADD COLUMN probe_kind VARCHAR(32) DEFAULT 'chat'")

    if not stmts:
        return

    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
        conn.execute(
            text(
                "UPDATE monitored_targets SET probe_kind = 'chat' "
                "WHERE probe_kind IS NULL OR TRIM(probe_kind) = ''"
            )
        )
        conn.execute(
            text(
                "UPDATE monitored_targets SET task_config_json = '{}' "
                "WHERE task_config_json IS NULL OR TRIM(task_config_json) = ''"
            )
        )
        conn.execute(
            text(
                "UPDATE measurements SET probe_kind = 'chat' "
                "WHERE probe_kind IS NULL OR TRIM(probe_kind) = ''"
            )
        )
