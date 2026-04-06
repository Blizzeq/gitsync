"""Tests for CLI commands and configuration helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path

from typer.testing import CliRunner

from gitsync import __main__ as main_module
from gitsync.cli import app
from gitsync.core.config import Settings
from gitsync.core.models import SyncStatus
from gitsync.core.storage import Storage

runner = CliRunner()


def test_settings_validation_and_directory_setup(tmp_path: Path) -> None:
    """Settings should validate required sync fields and prepare the DB directory."""
    settings = Settings(_env_file=None, db_path=tmp_path / "nested" / "gitsync.db")
    settings.ensure_directories()

    assert settings.db_path.parent.exists()

    try:
        settings.require_sync_configuration()
    except ValueError as exc:
        assert "GITSYNC_GITLAB_TOKEN" in str(exc)
        assert "GITSYNC_GITHUB_EMAIL" in str(exc)
    else:
        raise AssertionError("Expected missing configuration validation to fail")


def test_cli_init_writes_env_file(monkeypatch, test_settings, tmp_path: Path) -> None:
    """The init command should write an env file from interactive prompts."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr("gitsync.cli.get_settings", lambda: test_settings)

    result = runner.invoke(
        app,
        ["init", "--env-file", str(env_file)],
        input=(
            "https://gitlab.com\n"
            "jakub\n"
            "gitlab-token\n"
            "jakub/gitlab-activity\n"
            "github-token\n"
            "jakub@example.com\n"
            "main\n"
            f"{tmp_path / 'local.db'}\n"
        ),
    )

    assert result.exit_code == 0
    assert env_file.exists()
    content = env_file.read_text(encoding="utf-8")
    assert "GITSYNC_GITHUB_REPO=jakub/gitlab-activity" in content


def test_cli_status_sync_serve_and_main(monkeypatch, test_settings) -> None:
    """Core CLI commands should delegate to the expected runtime functions."""
    storage = Storage(test_settings.db_path)

    async def seed() -> None:
        await storage.initialize()
        sync_run = await storage.create_sync_run()
        await storage.finish_sync_run(
            sync_run.id or 0,
            status=SyncStatus.SUCCESS,
            events_synced=3,
        )

    asyncio.run(seed())
    monkeypatch.setattr("gitsync.cli.get_settings", lambda: test_settings)

    sync_called = {"value": False}

    async def fake_run_sync_command(settings: Settings) -> None:
        sync_called["value"] = settings.github_repo == test_settings.github_repo

    monkeypatch.setattr("gitsync.cli._run_sync_command", fake_run_sync_command)

    serve_called: dict[str, object] = {}

    def fake_create_app(settings: Settings) -> object:
        serve_called["app"] = settings.github_repo
        return object()

    def fake_uvicorn_run(
        application: object, host: str, port: int, log_level: str
    ) -> None:
        serve_called["host"] = host
        serve_called["port"] = port
        serve_called["log_level"] = log_level

    monkeypatch.setattr("gitsync.cli.create_app", fake_create_app)
    monkeypatch.setattr("gitsync.cli.uvicorn.run", fake_uvicorn_run)

    status_result = runner.invoke(app, ["status"])
    sync_result = runner.invoke(app, ["sync"])
    serve_result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])

    called = {"value": False}
    monkeypatch.setattr(main_module, "app", lambda: called.__setitem__("value", True))
    main_module.main()

    assert status_result.exit_code == 0
    assert "status=success" in status_result.stdout
    assert sync_result.exit_code == 0
    assert sync_called["value"] is True
    assert serve_result.exit_code == 0
    assert serve_called == {
        "app": "jakub/gitlab-activity",
        "host": "0.0.0.0",
        "port": 9000,
        "log_level": "info",
    }
    assert called["value"] is True
