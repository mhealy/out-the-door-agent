from sqlalchemy import inspect

from app.persistence.db import build_engine, create_schema


def test_create_schema_creates_purchase_runs_table() -> None:
    engine = build_engine("sqlite://")
    create_schema(engine)

    assert "purchase_runs" in inspect(engine).get_table_names()
