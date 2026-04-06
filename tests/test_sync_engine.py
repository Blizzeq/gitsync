"""Tests for the sync orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gitsync.core.models import EventType, GitLabEvent, SyncStatus
from gitsync.core.storage import Storage
from gitsync.core.sync_engine import SyncEngine


class FakeGitLabClient:
    """Return a fixed set of events for sync tests."""

    def __init__(self, events: list[GitLabEvent]) -> None:
        self.events = events

    async def fetch_all_activity(self, after=None, before=None) -> list[GitLabEvent]:
        return self.events


class FakeGitHubClient:
    """Collect mirrored commits without touching git."""

    def __init__(self) -> None:
        self.created_messages: list[str] = []
        self.push_called = False
        self.cleaned_up = False

    async def create_contribution(self, event: GitLabEvent) -> str:
        self.created_messages.append(event.commit_message)
        return f"sha-{len(self.created_messages)}"

    async def push_contributions(self) -> None:
        self.push_called = True

    async def cleanup(self) -> None:
        self.cleaned_up = True


@pytest.mark.asyncio
async def test_sync_engine_mirrors_only_new_events(test_settings) -> None:
    """The sync engine should store events and push once per run."""
    storage = Storage(test_settings.db_path)
    events = [
        GitLabEvent(
            source_id="commit:1",
            event_type=EventType.COMMIT,
            title="Initial sync",
            project_name="group/project",
            timestamp=datetime(2026, 4, 5, 8, 0, tzinfo=UTC),
        ),
        GitLabEvent(
            source_id="issue:1",
            event_type=EventType.ISSUE_CREATED,
            title="Login fails on Safari",
            project_name="group/project",
            timestamp=datetime(2026, 4, 5, 9, 0, tzinfo=UTC),
        ),
    ]
    github_client = FakeGitHubClient()
    engine = SyncEngine(
        gitlab_client=FakeGitLabClient(events),
        github_client=github_client,
        storage=storage,
    )

    sync_run = await engine.run_sync()

    assert sync_run.status is SyncStatus.SUCCESS
    assert sync_run.events_synced == 2
    assert github_client.push_called is True
    assert github_client.cleaned_up is True
    assert await storage.count_activity() == 2


@pytest.mark.asyncio
async def test_sync_engine_skips_known_events(test_settings) -> None:
    """Previously stored events should not create duplicate contributions."""
    storage = Storage(test_settings.db_path)
    await storage.initialize()
    sync_run = await storage.create_sync_run()
    event = GitLabEvent(
        source_id="commit:already-synced",
        event_type=EventType.COMMIT,
        title="Already mirrored",
        project_name="group/project",
        timestamp=datetime(2026, 4, 5, 10, 0, tzinfo=UTC),
    )
    await storage.save_activity(event, sync_run_id=sync_run.id or 0, github_sha="sha-0")

    github_client = FakeGitHubClient()
    engine = SyncEngine(
        gitlab_client=FakeGitLabClient([event]),
        github_client=github_client,
        storage=storage,
    )
    result = await engine.run_sync()

    assert result.events_synced == 0
    assert github_client.created_messages == []
    assert github_client.push_called is False
