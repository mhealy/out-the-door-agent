from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.demo import DemoSafetyError, main, preflight_demo, reset_demo
from app.persistence.db import build_engine, create_schema
from app.persistence.models import Base, PurchaseRun
from app.providers.followup_drafting import OpenAIFollowupDrafter
from app.providers.quote_extraction import OpenAIQuoteExtractor
from app.providers.research_synthesis import OpenAIResearchSynthesizer


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _settings(
    tmp_path: Path,
    *,
    environment: str = "test",
    database_url: str | None = None,
    checkpoint_path: Path | None = None,
    with_model_key: bool = True,
) -> Settings:
    application_database = tmp_path / "out_the_door.db"
    return Settings(
        environment=environment,
        database_url=(
            database_url
            if database_url is not None
            else f"sqlite:///{application_database}"
        ),
        langgraph_checkpoint_path=(
            checkpoint_path
            if checkpoint_path is not None
            else tmp_path / "out_the_door_checkpoints.db"
        ),
        openai_api_key=(
            SecretStr("configured-presence-only") if with_model_key else None
        ),
    )


def _fixture_hashes() -> dict[Path, str]:
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((REPOSITORY_ROOT / "demo").rglob("*.json"))
    }


def _seed_application_database(settings: Settings) -> None:
    engine = build_engine(settings.database_url)
    try:
        create_schema(engine)
        with Session(engine) as session:
            session.add(PurchaseRun(id="stale-purchase", goal="stale", status="CREATED"))
            session.commit()
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE unrelated_app_state (value TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO unrelated_app_state (value) VALUES ('preserve me')"
            )
    finally:
        engine.dispose()


def _seed_checkpoint_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB,
                metadata BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            );
            CREATE TABLE writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                value BLOB,
                PRIMARY KEY (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    task_id,
                    idx
                )
            );
            CREATE TABLE unrelated_checkpoint_state (value TEXT NOT NULL);
            INSERT INTO checkpoints (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                type,
                checkpoint,
                metadata
            ) VALUES ('thread', '', 'checkpoint', 'json', X'00', X'00');
            INSERT INTO writes (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                task_id,
                idx,
                channel,
                type,
                value
            ) VALUES ('thread', '', 'checkpoint', 'task', 0, 'route', 'json', X'00');
            INSERT INTO unrelated_checkpoint_state (value) VALUES ('preserve me');
            """
        )


def _check_map(report: object) -> dict[str, object]:
    checks = getattr(report, "checks")
    return {check.name: check for check in checks}


def test_expected_fixture_path_searches_ancestors_in_docker_layout(
    tmp_path: Path,
) -> None:
    from app.demo import _find_expected_fixture_path

    installed_module = tmp_path / "app" / "app" / "demo.py"
    expected = (
        tmp_path
        / "app"
        / "demo"
        / "expected"
        / "quote_analysis_expected.json"
    )
    installed_module.parent.mkdir(parents=True)
    installed_module.touch()
    expected.parent.mkdir(parents=True)
    expected.write_text("[]", encoding="utf-8")

    assert _find_expected_fixture_path(installed_module) == expected


def test_reset_clears_known_state_and_recreates_both_usable_schemas(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    application_path = tmp_path / "out_the_door.db"
    checkpoint_path = tmp_path / "out_the_door_checkpoints.db"
    _seed_application_database(settings)
    _seed_checkpoint_database(checkpoint_path)
    fixture_hashes = _fixture_hashes()
    sentinel = tmp_path / "do-not-delete.txt"
    sentinel.write_text("preserve me", encoding="utf-8")

    report = reset_demo(settings)

    assert report.application_database == application_path.resolve()
    assert report.checkpoint_database == checkpoint_path.resolve()
    engine = build_engine(settings.database_url)
    try:
        assert set(Base.metadata.tables).issubset(set(inspect(engine).get_table_names()))
        with engine.begin() as connection:
            for table_name in Base.metadata.tables:
                assert connection.scalar(text(f'SELECT COUNT(*) FROM "{table_name}"')) == 0
            assert connection.scalar(
                text("SELECT value FROM unrelated_app_state")
            ) == "preserve me"

        with Session(engine) as session:
            session.add(
                PurchaseRun(
                    id="new-purchase",
                    goal="schema remains usable",
                    status="CREATED",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    with sqlite3.connect(checkpoint_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"checkpoints", "writes"}.issubset(tables)
        assert connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM writes").fetchone() == (0,)
        assert connection.execute(
            "SELECT value FROM unrelated_checkpoint_state"
        ).fetchone() == ("preserve me",)

    assert sentinel.read_text(encoding="utf-8") == "preserve me"
    assert _fixture_hashes() == fixture_hashes


def test_preflight_rejects_drifted_checkpoint_schema_and_reset_repairs_it(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    checkpoint_path = tmp_path / "out_the_door_checkpoints.db"
    engine = build_engine(settings.database_url)
    try:
        create_schema(engine)
    finally:
        engine.dispose()
    with sqlite3.connect(checkpoint_path) as connection:
        connection.executescript(
            """
            CREATE TABLE checkpoints (wrong_column TEXT);
            CREATE TABLE writes (wrong_column TEXT);
            CREATE TABLE unrelated_checkpoint_state (value TEXT NOT NULL);
            INSERT INTO unrelated_checkpoint_state (value) VALUES ('preserve me');
            """
        )

    before = preflight_demo(settings)

    assert _check_map(before)["LangGraph checkpoint database"].status == "FAIL"

    reset_demo(settings)

    with sqlite3.connect(checkpoint_path) as connection:
        checkpoint_columns = tuple(
            row[1] for row in connection.execute('PRAGMA table_info("checkpoints")')
        )
        write_columns = tuple(
            row[1] for row in connection.execute('PRAGMA table_info("writes")')
        )
        assert checkpoint_columns == (
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "parent_checkpoint_id",
            "type",
            "checkpoint",
            "metadata",
        )
        assert write_columns == (
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "idx",
            "channel",
            "type",
            "value",
        )
        assert connection.execute(
            "SELECT value FROM unrelated_checkpoint_state"
        ).fetchone() == ("preserve me",)

    after = preflight_demo(settings)
    assert _check_map(after)["LangGraph checkpoint database"].status == "PASS"


@pytest.mark.parametrize(
    "case",
    [
        "production",
        "non_sqlite",
        "application_memory",
        "checkpoint_memory",
        "shared_file",
        "checkpoint_directory",
    ],
)
def test_reset_refuses_unsafe_configuration_before_touching_files(
    tmp_path: Path,
    case: str,
) -> None:
    application_path = tmp_path / "out_the_door.db"
    checkpoint_path = tmp_path / "out_the_door_checkpoints.db"
    environment = "test"
    database_url = f"sqlite:///{application_path}"

    if case == "production":
        environment = "production"
    elif case == "non_sqlite":
        database_url = "postgresql://demo.invalid/out_the_door"
    elif case == "application_memory":
        database_url = "sqlite://"
    elif case == "checkpoint_memory":
        checkpoint_path = Path(":memory:")
    elif case == "shared_file":
        checkpoint_path = application_path
    elif case == "checkpoint_directory":
        checkpoint_path.mkdir()

    settings = _settings(
        tmp_path,
        environment=environment,
        database_url=database_url,
        checkpoint_path=checkpoint_path,
    )
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")

    with pytest.raises(DemoSafetyError):
        reset_demo(settings)

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_cli_rejects_an_arbitrary_path_argument_without_deleting_it(
    tmp_path: Path,
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("still here", encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        main(["reset", str(victim)])

    assert raised.value.code == 2
    assert victim.read_text(encoding="utf-8") == "still here"


def test_preflight_cli_reports_malformed_configuration_without_a_traceback() -> None:
    environment = os.environ.copy()
    environment["OTD_CORS_ORIGINS"] = "not-json"

    completed = subprocess.run(
        [sys.executable, "-m", "app.demo", "preflight"],
        cwd=REPOSITORY_ROOT / "backend",
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 1
    assert "FAIL  demo preflight" in output
    assert "Traceback" not in output


def test_healthy_preflight_is_observational_and_never_constructs_model_clients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    reset_demo(settings)

    def model_call_forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("Preflight must not construct or call a model client.")

    monkeypatch.setattr(OpenAIQuoteExtractor, "from_api_key", model_call_forbidden)
    monkeypatch.setattr(OpenAIFollowupDrafter, "from_api_key", model_call_forbidden)
    monkeypatch.setattr(
        OpenAIResearchSynthesizer,
        "from_api_key",
        model_call_forbidden,
    )

    application_before = Path(tmp_path / "out_the_door.db").read_bytes()
    checkpoint_before = Path(tmp_path / "out_the_door_checkpoints.db").read_bytes()
    report = preflight_demo(settings, frontend_api_target="http://localhost:8000")

    assert report.ready is True
    checks = _check_map(report)
    assert set(checks) == {
        "configuration",
        "canonical inventory",
        "dealer responses",
        "expected quote corpus",
        "research sources",
        "application database",
        "LangGraph checkpoint database",
        "frontend API target",
        "model credential configured",
    }
    assert all(check.status == "PASS" for check in checks.values())
    assert "presence only" in checks["model credential configured"].detail
    assert report.render().endswith("READY canonical demo")
    assert Path(tmp_path / "out_the_door.db").read_bytes() == application_before
    assert Path(tmp_path / "out_the_door_checkpoints.db").read_bytes() == checkpoint_before


def test_preflight_reads_frontend_target_from_repository_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    reset_demo(settings)
    repository_env = tmp_path / ".env"
    repository_env.write_text(
        "VITE_API_BASE_URL=https://reviewer-api.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("VITE_API_BASE_URL", raising=False)
    monkeypatch.setattr("app.demo.ROOT_ENV_FILE", repository_env)

    report = preflight_demo(settings)

    frontend = _check_map(report)["frontend API target"]
    assert frontend.status == "PASS"
    assert frontend.detail == "https://reviewer-api.example.test"


def test_preflight_rejects_blank_model_names_without_hiding_usable_stores(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).model_copy(
        update={"quote_extraction_model": "  "},
    )
    reset_demo(settings)

    report = preflight_demo(settings)

    checks = _check_map(report)
    assert checks["configuration"].status == "FAIL"
    assert "OTD_QUOTE_EXTRACTION_MODEL" in checks["configuration"].detail
    assert checks["application database"].status == "PASS"
    assert checks["LangGraph checkpoint database"].status == "PASS"
    assert report.ready is False


def test_preflight_releases_database_file_handles(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    reset_demo(settings)

    report = preflight_demo(settings)

    assert report.ready is True
    (tmp_path / "out_the_door.db").unlink()
    (tmp_path / "out_the_door_checkpoints.db").unlink()


def test_preflight_aggregates_missing_fixtures_and_unusable_stores_without_creating_them(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    missing_dealers = tmp_path / "missing-dealer-responses.json"
    missing_expected = tmp_path / "missing-expected-quotes.json"
    missing_research = tmp_path / "missing-research-sources.json"

    report = preflight_demo(
        settings,
        dealer_fixture_path=missing_dealers,
        expected_fixture_path=missing_expected,
        research_fixture_path=missing_research,
        frontend_api_target="ftp://invalid.example",
    )

    checks = _check_map(report)
    assert report.ready is False
    assert checks["configuration"].status == "PASS"
    assert checks["canonical inventory"].status == "PASS"
    for name in (
        "dealer responses",
        "expected quote corpus",
        "research sources",
        "application database",
        "LangGraph checkpoint database",
        "frontend API target",
    ):
        assert checks[name].status == "FAIL"
    assert report.render().endswith("NOT READY canonical demo")
    assert not (tmp_path / "out_the_door.db").exists()
    assert not (tmp_path / "out_the_door_checkpoints.db").exists()


def test_missing_model_key_is_truthful_not_ready_and_cli_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ready_settings = _settings(tmp_path)
    reset_demo(ready_settings)
    settings = _settings(tmp_path, with_model_key=False)

    report = preflight_demo(settings)

    model_check = _check_map(report)["model credential configured"]
    assert model_check.status == "FAIL"
    assert "not configured" in model_check.detail
    assert report.ready is False

    monkeypatch.setattr("app.demo.get_settings", lambda: settings)
    assert main(["preflight"]) == 1
    output = capsys.readouterr().out
    assert "FAIL  model credential configured" in output
    assert output.rstrip().endswith("NOT READY canonical demo")
