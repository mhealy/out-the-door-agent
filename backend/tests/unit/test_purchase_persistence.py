from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

import pytest

from app.persistence.agent_runs import AgentRunRepository
from app.persistence.db import build_engine, create_schema
from app.persistence.purchases import (
    PurchaseChildAlreadyLinkedError,
    PurchaseChildRunMismatchError,
    PurchaseRunRepository,
)


def _sessions() -> sessionmaker[Session]:
    engine = build_engine("sqlite://")
    create_schema(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_purchase_vehicle_intents_are_ordered_and_survive_session_recreation() -> None:
    sessions = _sessions()

    with sessions() as session:
        purchase = PurchaseRunRepository(session).create(
            goal="Compare three Tucson Hybrid offers",
            vehicle_ids=["baytown-blue", "houston-white", "katy-blue"],
        )
        purchase_id = purchase.id

    with sessions() as session:
        repository = PurchaseRunRepository(session)
        restored = repository.get(purchase_id)
        links = repository.list_vehicle_links(purchase_id)

    assert restored.goal == "Compare three Tucson Hybrid offers"
    assert [link.vehicle_id for link in links] == [
        "baytown-blue",
        "houston-white",
        "katy-blue",
    ]
    assert [link.position for link in links] == [0, 1, 2]
    assert [link.agent_run_id for link in links] == [None, None, None]


def test_child_attachment_is_idempotent_but_cannot_be_reassigned() -> None:
    sessions = _sessions()

    with sessions() as session:
        purchases = PurchaseRunRepository(session)
        purchase = purchases.create(
            goal="Compare Baytown and Houston",
            vehicle_ids=["baytown-blue", "houston-white"],
        )
        first_run = AgentRunRepository(session).create("baytown-blue")
        second_run = AgentRunRepository(session).create("baytown-blue")

        first = purchases.attach_agent_run(
            purchase.id,
            "baytown-blue",
            first_run.id,
        )
        repeated = purchases.attach_agent_run(
            purchase.id,
            "baytown-blue",
            first_run.id,
        )

        assert first.agent_run_id == first_run.id
        assert repeated.agent_run_id == first_run.id
        with pytest.raises(PurchaseChildAlreadyLinkedError):
            purchases.attach_agent_run(
                purchase.id,
                "baytown-blue",
                second_run.id,
            )


def test_child_attachment_rejects_a_run_for_another_selected_vehicle() -> None:
    sessions = _sessions()

    with sessions() as session:
        purchases = PurchaseRunRepository(session)
        purchase = purchases.create(
            goal="Compare Baytown and Houston",
            vehicle_ids=["baytown-blue", "houston-white"],
        )
        houston_run = AgentRunRepository(session).create("houston-white")

        with pytest.raises(PurchaseChildRunMismatchError):
            purchases.attach_agent_run(
                purchase.id,
                "baytown-blue",
                houston_run.id,
            )


def test_schema_enforces_one_vehicle_and_one_linked_run_per_purchase_child() -> None:
    engine = build_engine("sqlite://")
    create_schema(engine)

    tables = inspect(engine)
    assert "purchase_run_vehicles" in tables.get_table_names()
    unique_column_sets = {
        tuple(constraint["column_names"])
        for constraint in tables.get_unique_constraints("purchase_run_vehicles")
    }
    assert ("purchase_run_id", "vehicle_id") in unique_column_sets
    assert ("agent_run_id",) in unique_column_sets
