"""Tests for the main FastAPI routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from gitsync.core.models import EventType, GitLabEvent, SyncStatus
from gitsync.core.storage import Storage
from gitsync.web.app import create_app


def _seed_storage(test_settings, *, count: int = 1) -> None:
    """Insert sample data into storage for route tests."""
    storage = Storage(test_settings.db_path)

    async def _inner() -> None:
        await storage.initialize()
        sync_run = await storage.create_sync_run()
        for i in range(count):
            await storage.save_activity(
                GitLabEvent(
                    source_id=f"commit:abc{i}",
                    event_type=EventType.COMMIT,
                    title=f"Fix database pooling #{i}",
                    project_name="group/project",
                    timestamp=datetime(2026, 4, 6, 8, i, tzinfo=UTC),
                ),
                sync_run_id=sync_run.id or 0,
                github_sha=f"sha-{i}",
            )
        await storage.finish_sync_run(
            sync_run.id or 0,
            status=SyncStatus.SUCCESS,
            events_synced=count,
        )

    asyncio.run(_inner())


def test_web_routes_render_and_accept_settings(test_settings) -> None:
    """Dashboard, activity, settings and health endpoints should be available."""
    _seed_storage(test_settings)
    app = create_app(test_settings)

    with TestClient(app) as client:
        dashboard = client.get("/")
        activity = client.get("/activity")
        settings = client.get("/settings")
        health = client.get("/api/health")
        settings_update = client.post(
            "/settings",
            data={
                "gitlab_url": "https://gitlab.com",
                "gitlab_username": "jakub",
                "github_repo": "jakub/gitlab-activity",
                "github_email": "jakub@example.com",
                "github_branch": "main",
                "sync_commits": "on",
                "sync_merge_requests": "on",
            },
            headers={"HX-Request": "true"},
        )

    assert dashboard.status_code == 200
    assert "Contribution rhythm" in dashboard.text
    assert activity.status_code == 200
    assert "Fix database pooling" in activity.text
    assert settings.status_code == 200
    assert "Runtime settings" in settings.text
    assert health.json() == {"status": "ok"}
    assert settings_update.status_code == 200
    assert "Configuration saved" in settings_update.text


def test_sync_status_partial(test_settings) -> None:
    """The HTMX sync status partial should return valid HTML."""
    _seed_storage(test_settings)
    app = create_app(test_settings)

    with TestClient(app) as client:
        response = client.get("/partials/sync-status")

    assert response.status_code == 200
    assert "Sync status" in response.text
    assert "Success" in response.text


def test_activity_rows_partial(test_settings) -> None:
    """The HTMX activity rows partial should return table rows."""
    _seed_storage(test_settings, count=5)
    app = create_app(test_settings)

    with TestClient(app) as client:
        response = client.get("/activity/rows?page=1&per_page=3")

    assert response.status_code == 200
    assert "group/project" in response.text


def test_activity_filter_by_event_type(test_settings) -> None:
    """Activity page should accept event_type and search filters."""
    _seed_storage(test_settings, count=3)
    app = create_app(test_settings)

    with TestClient(app) as client:
        response = client.get("/activity?event_type=commit&search=pooling")

    assert response.status_code == 200
    assert "Fix database pooling" in response.text


def test_api_trigger_sync_success(test_settings) -> None:
    """POST /api/sync should run a sync and return the status partial."""
    _seed_storage(test_settings)
    app = create_app(test_settings)

    mock_run = AsyncMock(
        return_value=type(
            "FakeSyncRun",
            (),
            {"status": SyncStatus.SUCCESS, "events_synced": 3},
        )()
    )

    with TestClient(app) as client:
        with patch("gitsync.web.routes.api.build_sync_engine") as mock_build:
            mock_engine = AsyncMock()
            mock_engine.run_sync = mock_run
            mock_build.return_value = mock_engine
            response = client.post("/api/sync")

    assert response.status_code == 200
    assert "3 events mirrored" in response.text


def test_api_trigger_sync_failure(test_settings) -> None:
    """POST /api/sync should handle sync errors gracefully."""
    _seed_storage(test_settings)
    app = create_app(test_settings)

    with TestClient(app) as client:
        with patch("gitsync.web.routes.api.build_sync_engine") as mock_build:
            mock_engine = AsyncMock()
            mock_engine.run_sync = AsyncMock(
                side_effect=RuntimeError("GitLab unreachable")
            )
            mock_build.return_value = mock_engine
            response = client.post("/api/sync")

    assert response.status_code == 200
    assert "Sync failed" in response.text
    assert "GitLab unreachable" in response.text


def test_settings_test_connection_missing_config(test_settings) -> None:
    """Test connection should fail when required tokens are missing."""
    test_settings.gitlab_token = None
    app = create_app(test_settings)

    with TestClient(app) as client:
        response = client.post("/settings/test")

    assert response.status_code == 200
    assert "failed" in response.text.lower()
