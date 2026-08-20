from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

import pytest

from app.persistence.agent_runs import AgentRunRepository
from app.persistence.db import build_engine, create_schema
from app.persistence.purchases import (
    PurchaseChildAlreadyLinkedError,
    PurchaseChildRunMismatchError,
    PurchaseCreationConflictError,
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
            creation_id="7ba9b12f-414d-40db-a541-9f9a31a7db10",
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
            creation_id="3c803cac-107d-497c-91a6-c3506ffca0f4",
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
            creation_id="aa5c2130-28bb-447d-9a4e-a4cbe90f4407",
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


def test_creation_identity_returns_one_purchase_for_the_same_normalized_intent() -> None:
    sessions = _sessions()
    creation_id = "8c921f9f-4c3d-4e52-aa5f-226f27fe61cf"

    with sessions() as session:
        purchases = PurchaseRunRepository(session)
        first = purchases.create(
            creation_id=creation_id,
            goal="  Compare Baytown and Houston  ",
            vehicle_ids=["baytown-blue", "houston-white"],
        )
        repeated = purchases.create(
            creation_id=creation_id,
            goal="Compare Baytown and Houston",
            vehicle_ids=["baytown-blue", "houston-white"],
        )

        assert first.id == creation_id
        assert repeated.id == first.id
        assert repeated.goal == "Compare Baytown and Houston"
        assert [
            link.vehicle_id for link in purchases.list_vehicle_links(first.id)
        ] == ["baytown-blue", "houston-white"]

    with sessions() as session:
        assert session.execute(
            text("select count(*) from purchase_runs")
        ).scalar_one() == 1
        assert session.execute(
            text("select count(*) from purchase_run_vehicles")
        ).scalar_one() == 2


@pytest.mark.parametrize(
    ("goal", "vehicle_ids"),
    [
        (
            "Compare Baytown and Katy",
            ["baytown-blue", "houston-white"],
        ),
        (
            "Compare Baytown and Houston",
            ["houston-white", "baytown-blue"],
        ),
        (
            "Compare Baytown and Houston",
            ["baytown-blue", "katy-blue"],
        ),
    ],
)
def test_creation_identity_rejects_a_different_normalized_or_ordered_intent(
    goal: str,
    vehicle_ids: list[str],
) -> None:
    sessions = _sessions()
    creation_id = "cd5da45e-8b69-4d74-982e-a46666807b6a"

    with sessions() as session:
        purchases = PurchaseRunRepository(session)
        original = purchases.create(
            creation_id=creation_id,
            goal="Compare Baytown and Houston",
            vehicle_ids=["baytown-blue", "houston-white"],
        )

        with pytest.raises(PurchaseCreationConflictError):
            purchases.create(
                creation_id=creation_id,
                goal=goal,
                vehicle_ids=vehicle_ids,
            )

        assert purchases.get(creation_id) == original
        assert [
            link.vehicle_id for link in purchases.list_vehicle_links(creation_id)
        ] == ["baytown-blue", "houston-white"]
