"""Tests for SQLite storage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gitsync.core.models import EventType, GitLabEvent, SyncStatus
from gitsync.core.storage import Storage


@pytest.mark.asyncio
async def test_storage_persists_runs_and_activity(test_settings) -> None:
    """Storage should persist sync runs and mirrored activity rows."""
    storage = Storage(test_settings.db_path)
    await storage.initialize()

    sync_run = await storage.create_sync_run()
    event = GitLabEvent(
        source_id="commit:abc123",
        event_type=EventType.COMMIT,
        title="Fix database pooling",
        project_name="group/project",
        timestamp=datetime(2026, 4, 6, 12, 0, tzinfo=UTC),
        url="https://gitlab.example/commit/abc123",
    )
    await storage.save_activity(event, sync_run_id=sync_run.id or 0, github_sha="sha-1")
    finished = await storage.finish_sync_run(
        sync_run.id or 0,
        status=SyncStatus.SUCCESS,
        events_synced=1,
    )

    assert finished.status is SyncStatus.SUCCESS
    assert await storage.activity_exists(event.source_id) is True
    assert await storage.count_activity() == 1

    snapshot = await storage.get_dashboard_snapshot(days=7)
    assert snapshot.total_events == 1
    assert snapshot.last_sync is not None
    assert snapshot.last_sync.status is SyncStatus.SUCCESS
    assert snapshot.recent_events[0].title == "Fix database pooling"
