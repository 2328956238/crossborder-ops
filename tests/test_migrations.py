# -*- coding: utf-8 -*-
"""数据库迁移：空库 upgrade head 建全表，downgrade base 可回退。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "shops", "platform_event", "orders", "sync_cursor", "inventory", "ad_report",
    "operation", "operation_audit",
}


def test_upgrade_head_on_empty_db(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    db_path = tmp_path / "migrate.db"
    monkeypatch.setenv("ALEMBIC_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES <= tables

    # 约束与索引必须落到库里（不是只在 ORM 里声明）
    order_indexes = {i["name"] for i in inspector.get_indexes("orders")}
    assert any("shop" in name for name in order_indexes) or any(
        c["column_names"] == ["shop_id"] for c in inspector.get_indexes("orders"))
    op_indexes = {i["name"] for i in inspector.get_indexes("operation")}
    assert "ix_operation_shop_status" in op_indexes
    uniques = {u["name"] for u in inspector.get_unique_constraints("operation")}
    assert "uq_operation_idem" in uniques
    assert "uq_event" in {u["name"] for u in inspector.get_unique_constraints("platform_event")}

    command.downgrade(config, "base")
    assert not (EXPECTED_TABLES & set(inspect(create_engine(
        f"sqlite:///{db_path.as_posix()}")).get_table_names()))


def test_alembic_config_points_to_package_metadata():
    """防止有人把 env.py 指回旧 hub.models。"""
    env_text = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "crossborder_ops.models" in env_text
    assert "import hub" not in env_text


def test_upgrade_over_phase1_existing_rows(tmp_path, monkeypatch):
    """已有数据（阶段 1 的表 + 行）也能升级到最新：新列必须有默认值。"""
    import sqlite3

    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("ALEMBIC_DB_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))

    command.upgrade(config, "5731fe8e390b")
    conn = sqlite3.connect(db_path)
    conn.execute("insert into shops (id,name,marketplace,currency,timezone,status) "
                 "values ('S1','Shop','amazon','USD','UTC','active')")
    conn.execute("insert into orders (shop_id,order_id,status,last_update_time,version) "
                 "values ('S1','O-LEGACY','PENDING','2026-01-01T00:00:00+00:00',1)")
    conn.commit()
    conn.close()

    command.upgrade(config, "head")
    conn = sqlite3.connect(db_path)
    row = conn.execute("select total_amount, currency from orders where order_id='O-LEGACY'").fetchone()
    conn.close()
    assert row == (0, "USD")
