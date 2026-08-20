from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from dotenv import dotenv_values
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config import ROOT_ENV_FILE, Settings, get_settings
from app.domain.criteria import VehicleSearchCriteria
from app.domain.research import ResearchRequest
from app.persistence.models import Base
from app.providers.dealer_messages import (
    DEFAULT_FIXTURE_PATH,
    DEMO_RESPONSE_FIXTURE_IDS,
    FixtureDealerMessageProvider,
)
from app.providers.inventory import FixtureInventoryProvider
from app.providers.quote_extraction import QuoteExtractorOutput
from app.providers.research import (
    DEFAULT_RESEARCH_FIXTURE_PATH,
    FixtureResearchProvider,
)


_EXPECTED_FIXTURE_RELATIVE_PATH = Path(
    "demo/expected/quote_analysis_expected.json"
)


def _find_expected_fixture_path(module_path: Path = Path(__file__)) -> Path:
    for parent in module_path.resolve().parents:
        candidate = parent / _EXPECTED_FIXTURE_RELATIVE_PATH
        if candidate.exists():
            return candidate
    return module_path.resolve().parents[2] / _EXPECTED_FIXTURE_RELATIVE_PATH


DEFAULT_EXPECTED_FIXTURE_PATH = _find_expected_fixture_path()

_LOCAL_ENVIRONMENTS = frozenset({"development", "demo", "local", "test"})
_CHECKPOINT_TABLES = frozenset({"checkpoints", "writes"})
_CHECKPOINT_REQUIRED_COLUMNS = {
    "checkpoints": (
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "parent_checkpoint_id",
        "type",
        "checkpoint",
        "metadata",
    ),
    "writes": (
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "task_id",
        "idx",
        "channel",
        "type",
        "value",
    ),
}
_CHECKPOINT_PRIMARY_KEYS = {
    "checkpoints": ("thread_id", "checkpoint_ns", "checkpoint_id"),
    "writes": (
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "task_id",
        "idx",
    ),
}
_CANONICAL_INVENTORY = {
    "baytown-blue": Decimal("37800"),
    "houston-white": Decimal("37250"),
    "katy-blue": Decimal("39500"),
}
_CANONICAL_RESPONSES = {
    ("baytown", "baytown-blue"): "msg-explicit-no-addons",
    ("houston", "houston-white"): "msg-mandatory-addons",
    ("katy", "katy-blue"): "msg-trade-assistance",
}
_CANONICAL_OTD = {
    "msg-explicit-no-addons": Decimal("40315"),
    "msg-mandatory-addons": Decimal("41780"),
    "msg-trade-assistance": Decimal("40250"),
}
_CANONICAL_RESEARCH_TARGETS = (
    "Ceramic Shield",
    "SecureTrack theft recovery",
)
_MODEL_SETTINGS = (
    ("quote_extraction_model", "OTD_QUOTE_EXTRACTION_MODEL"),
    ("followup_drafting_model", "OTD_FOLLOWUP_DRAFTING_MODEL"),
    ("research_synthesis_model", "OTD_RESEARCH_SYNTHESIS_MODEL"),
)


class DemoSafetyError(RuntimeError):
    """The configured target is outside the intentionally narrow demo boundary."""


@dataclass(frozen=True)
class ResetReport:
    application_database: Path
    checkpoint_database: Path
    application_table_count: int

    def render(self) -> str:
        return "\n".join(
            (
                f"RESET application database - {self.application_database}",
                f"RESET LangGraph checkpoint database - {self.checkpoint_database}",
                "READY clean demo state",
            )
        )


CheckStatus = Literal["PASS", "FAIL"]


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.status == "PASS" for check in self.checks)

    def render(self) -> str:
        lines = [
            f"{check.status:<6}{check.name} - {check.detail}"
            for check in self.checks
        ]
        lines.extend(
            (
                "",
                "READY canonical demo"
                if self.ready
                else "NOT READY canonical demo",
            )
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class _DemoTargets:
    application_database: Path
    checkpoint_database: Path


def _configured_sqlite_path(database_url: str) -> Path:
    try:
        url = make_url(database_url)
    except Exception as error:
        raise DemoSafetyError("The application database URL is invalid.") from error
    if url.get_backend_name() != "sqlite":
        raise DemoSafetyError("Demo tooling supports only application SQLite.")
    if url.database is None or url.database.strip() in {"", ":memory:"}:
        raise DemoSafetyError("The application SQLite database must be file-backed.")
    if url.query.get("mode") == "memory":
        raise DemoSafetyError("The application SQLite database must be file-backed.")
    return _resolve_safe_file(Path(url.database), "application database")


def _configured_checkpoint_path(checkpoint_path: Path) -> Path:
    if str(checkpoint_path).strip() in {"", ":memory:"}:
        raise DemoSafetyError("The checkpoint SQLite database must be file-backed.")
    return _resolve_safe_file(checkpoint_path, "checkpoint database")


def _resolve_safe_file(path: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else Path.cwd() / path
    resolved = candidate.resolve(strict=False)
    if candidate.is_symlink():
        raise DemoSafetyError(f"The {label} must not be a symbolic link.")
    if resolved.exists() and not resolved.is_file():
        raise DemoSafetyError(f"The {label} target is not a regular file.")
    if not resolved.parent.exists() or not resolved.parent.is_dir():
        raise DemoSafetyError(f"The {label} parent directory does not exist.")
    return resolved


def _demo_targets(settings: Settings) -> _DemoTargets:
    environment = settings.environment.strip().casefold()
    if environment not in _LOCAL_ENVIRONMENTS:
        raise DemoSafetyError(
            "Demo tooling is restricted to development, demo, local, or test."
        )
    application_database = _configured_sqlite_path(settings.database_url)
    checkpoint_database = _configured_checkpoint_path(
        settings.langgraph_checkpoint_path
    )
    if application_database == checkpoint_database:
        raise DemoSafetyError(
            "Application and LangGraph checkpoint SQLite files must be distinct."
        )
    return _DemoTargets(application_database, checkpoint_database)


def _configuration_detail(settings: Settings) -> str:
    blank_model_settings = [
        environment_name
        for attribute_name, environment_name in _MODEL_SETTINGS
        if not str(getattr(settings, attribute_name)).strip()
    ]
    if blank_model_settings:
        raise DemoSafetyError(
            "Model configuration must be non-empty: "
            + ", ".join(blank_model_settings)
        )
    return f"{settings.environment} with distinct file-backed SQLite stores"


async def _recreate_checkpoint_database(path: Path) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        await checkpointer.conn.execute("DROP TABLE IF EXISTS writes")
        await checkpointer.conn.execute("DROP TABLE IF EXISTS checkpoints")
        await checkpointer.conn.commit()
        await checkpointer.setup()


def reset_demo(settings: Settings) -> ResetReport:
    """Clear only known local application and checkpoint state, then verify it."""

    targets = _demo_targets(settings)
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        table_names = set(inspect(engine).get_table_names())
        missing = set(Base.metadata.tables) - table_names
        if missing:
            raise RuntimeError(
                "Application schema recreation omitted: " + ", ".join(sorted(missing))
            )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()

    asyncio.run(_recreate_checkpoint_database(targets.checkpoint_database))
    _inspect_sqlite_store(
        targets.checkpoint_database,
        _CHECKPOINT_TABLES,
        required_columns=_CHECKPOINT_REQUIRED_COLUMNS,
        primary_keys=_CHECKPOINT_PRIMARY_KEYS,
    )
    return ResetReport(
        application_database=targets.application_database,
        checkpoint_database=targets.checkpoint_database,
        application_table_count=len(Base.metadata.tables),
    )


def _check_detail(error: Exception) -> str:
    message = " ".join(str(error).split())
    return message or type(error).__name__


def _run_check(
    checks: list[PreflightCheck],
    name: str,
    operation: Callable[[], str],
) -> None:
    try:
        detail = operation()
    except Exception as error:
        checks.append(PreflightCheck(name, "FAIL", _check_detail(error)))
    else:
        checks.append(PreflightCheck(name, "PASS", detail))


async def _canonical_inventory_detail() -> str:
    provider = FixtureInventoryProvider()
    listings = await provider.search(
        VehicleSearchCriteria(
            make="Hyundai",
            model="Tucson Hybrid",
            trims=["Limited"],
            condition="new",
            home_location="Houston, TX",
            max_distance_miles=50,
        )
    )
    by_id = {listing.id: listing for listing in listings}
    if len(by_id) != len(listings):
        raise ValueError("Inventory fixture IDs are not unique.")
    for vehicle_id, advertised_price in _CANONICAL_INVENTORY.items():
        listing = by_id.get(vehicle_id)
        if listing is None:
            raise ValueError(f"Canonical vehicle {vehicle_id} is missing.")
        if listing.advertised_price != advertised_price:
            raise ValueError(f"Canonical vehicle {vehicle_id} economics changed.")
    return "Baytown, Houston, and Katy inventory economics loaded"


async def _dealer_response_detail(fixture_path: Path) -> str:
    provider = FixtureDealerMessageProvider(fixture_path)
    messages = await provider.list_messages()
    by_id = {message.id: message for message in messages}
    if len(by_id) != len(messages):
        raise ValueError("Dealer-response fixture IDs are not unique.")
    if DEMO_RESPONSE_FIXTURE_IDS != _CANONICAL_RESPONSES:
        raise ValueError("Canonical dealer-response target mapping changed.")
    for (dealer_id, vehicle_id), message_id in _CANONICAL_RESPONSES.items():
        message = by_id.get(message_id)
        if message is None:
            raise ValueError(f"Canonical dealer response {message_id} is missing.")
        if message.dealer_id != dealer_id or message.vehicle_id != vehicle_id:
            raise ValueError(f"Canonical dealer response {message_id} was retargeted.")
    return f"{len(messages)} responses loaded; canonical mappings present"


def _expected_quote_detail(fixture_path: Path) -> str:
    records = json.loads(fixture_path.read_text(encoding="utf-8"))
    outputs: dict[str, QuoteExtractorOutput] = {}
    for record in records:
        case_id = str(record["case_id"])
        if case_id in outputs:
            raise ValueError("Expected quote fixture case IDs are not unique.")
        outputs[case_id] = QuoteExtractorOutput.model_validate(
            {
                "extraction": record["extraction"],
                "evidence": record["evidence"],
            }
        )
    for message_id, claimed_otd in _CANONICAL_OTD.items():
        output = outputs.get(message_id)
        if output is None:
            raise ValueError(f"Expected quote output {message_id} is missing.")
        if output.extraction.claimed_otd != claimed_otd:
            raise ValueError(f"Expected quote output {message_id} economics changed.")

    baytown = outputs["msg-explicit-no-addons"].extraction
    houston = outputs["msg-mandatory-addons"].extraction
    katy = outputs["msg-trade-assistance"].extraction
    if baytown.addons or not baytown.explicit_no_addons_statement:
        raise ValueError("Canonical Baytown no-add-on evidence changed.")
    houston_addons = {
        item.name: item.amount
        for item in houston.addons
        if item.stated_mandatory is True
    }
    if houston_addons != {
        "Ceramic Shield": Decimal("1299"),
        "SecureTrack theft recovery": Decimal("596"),
    }:
        raise ValueError("Canonical Houston mandatory add-ons changed.")
    if katy.vehicle_vin is not None or katy.explicit_no_addons_statement:
        raise ValueError("Canonical Katy uncertainty changed.")
    return f"{len(outputs)} labeled outputs loaded; canonical economics preserved"


async def _research_source_detail(fixture_path: Path) -> str:
    provider = FixtureResearchProvider(fixture_path)
    source_count = 0
    for canonical_name in _CANONICAL_RESEARCH_TARGETS:
        result = await provider.research(
            ResearchRequest(
                target_id=f"preflight-{canonical_name.casefold().replace(' ', '-')}",
                target_type="MANDATORY_ADDON",
                canonical_name=canonical_name,
            )
        )
        if not result.sources:
            raise ValueError(f"Research sources for {canonical_name} are empty.")
        source_count += len(result.sources)
    return f"{source_count} bounded sources loaded for both Houston add-ons"


def _inspect_sqlite_store(
    path: Path,
    expected_tables: frozenset[str] | set[str],
    *,
    required_columns: dict[str, tuple[str, ...]] | None = None,
    primary_keys: dict[str, tuple[str, ...]] | None = None,
) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"SQLite file does not exist: {path}")
    uri = f"{path.as_uri()}?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check != ("ok",):
            raise RuntimeError("SQLite quick_check did not return ok.")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = set(expected_tables) - tables
        if missing:
            raise RuntimeError("Missing SQLite tables: " + ", ".join(sorted(missing)))
        for table_name, expected_columns in (required_columns or {}).items():
            table_info = connection.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()
            actual_columns = {str(row[1]) for row in table_info}
            missing_columns = set(expected_columns) - actual_columns
            if missing_columns:
                raise RuntimeError(
                    f"SQLite table {table_name} is missing columns: "
                    + ", ".join(sorted(missing_columns))
                )
            expected_primary_key = (primary_keys or {}).get(table_name)
            if expected_primary_key is not None:
                actual_primary_key = tuple(
                    str(row[1])
                    for row in sorted(table_info, key=lambda row: int(row[5]))
                    if int(row[5]) > 0
                )
                if actual_primary_key != expected_primary_key:
                    raise RuntimeError(
                        f"SQLite table {table_name} has an incompatible primary key."
                    )
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()
    return f"usable file-backed SQLite at {path}"


def _frontend_target_detail(target: str) -> str:
    normalized = target.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Frontend API target must be an absolute HTTP(S) URL.")
    return normalized


def _configured_frontend_api_target() -> str:
    process_value = os.getenv("VITE_API_BASE_URL")
    if process_value is not None:
        return process_value
    file_value = dotenv_values(ROOT_ENV_FILE).get("VITE_API_BASE_URL")
    if file_value is not None:
        return file_value
    return "http://localhost:8000"


def preflight_demo(
    settings: Settings,
    *,
    dealer_fixture_path: Path = DEFAULT_FIXTURE_PATH,
    expected_fixture_path: Path = DEFAULT_EXPECTED_FIXTURE_PATH,
    research_fixture_path: Path = DEFAULT_RESEARCH_FIXTURE_PATH,
    frontend_api_target: str | None = None,
) -> PreflightReport:
    """Inspect canonical demo prerequisites without creating state or calling a model."""

    checks: list[PreflightCheck] = []
    targets: _DemoTargets | None = None
    try:
        targets = _demo_targets(settings)
    except Exception as error:
        checks.append(PreflightCheck("configuration", "FAIL", _check_detail(error)))
    else:
        _run_check(
            checks,
            "configuration",
            lambda: _configuration_detail(settings),
        )

    _run_check(
        checks,
        "canonical inventory",
        lambda: asyncio.run(_canonical_inventory_detail()),
    )
    _run_check(
        checks,
        "dealer responses",
        lambda: asyncio.run(_dealer_response_detail(dealer_fixture_path)),
    )
    _run_check(
        checks,
        "expected quote corpus",
        lambda: _expected_quote_detail(expected_fixture_path),
    )
    _run_check(
        checks,
        "research sources",
        lambda: asyncio.run(_research_source_detail(research_fixture_path)),
    )

    if targets is None:
        checks.extend(
            (
                PreflightCheck(
                    "application database",
                    "FAIL",
                    "Configuration did not resolve a safe application SQLite file.",
                ),
                PreflightCheck(
                    "LangGraph checkpoint database",
                    "FAIL",
                    "Configuration did not resolve a safe checkpoint SQLite file.",
                ),
            )
        )
    else:
        _run_check(
            checks,
            "application database",
            lambda: _inspect_sqlite_store(
                targets.application_database,
                set(Base.metadata.tables),
            ),
        )
        _run_check(
            checks,
            "LangGraph checkpoint database",
            lambda: _inspect_sqlite_store(
                targets.checkpoint_database,
                _CHECKPOINT_TABLES,
                required_columns=_CHECKPOINT_REQUIRED_COLUMNS,
                primary_keys=_CHECKPOINT_PRIMARY_KEYS,
            ),
        )

    _run_check(
        checks,
        "frontend API target",
        lambda: _frontend_target_detail(
            frontend_api_target
            if frontend_api_target is not None
            else _configured_frontend_api_target()
        ),
    )

    model_key = (
        settings.openai_api_key.get_secret_value().strip()
        if settings.openai_api_key is not None
        else ""
    )
    if model_key:
        checks.append(
            PreflightCheck(
                "model credential configured",
                "PASS",
                "OTD_OPENAI_API_KEY is present; presence only, no model call made",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "model credential configured",
                "FAIL",
                (
                    "OTD_OPENAI_API_KEY is not configured; model-backed analysis, "
                    "follow-up drafting, and research synthesis are unavailable"
                ),
            )
        )
    return PreflightReport(tuple(checks))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.demo",
        description="Local-only OutTheDoor canonical demo tooling.",
    )
    parser.add_argument("command", choices=("reset", "preflight"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        settings = get_settings()
        if arguments.command == "reset":
            print(reset_demo(settings).render())
            return 0
        report = preflight_demo(settings)
        print(report.render())
        return 0 if report.ready else 1
    except Exception as error:
        print(f"FAIL  demo {arguments.command} - {_check_detail(error)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
