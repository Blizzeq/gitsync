"""Domain models used across GitSync."""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """Supported GitLab activity types."""

    COMMIT = "commit"
    MR_CREATED = "mr-created"
    MR_MERGED = "mr-merged"
    MR_REVIEWED = "mr-reviewed"
    ISSUE_CREATED = "issue-created"
    ISSUE_CLOSED = "issue-closed"
    COMMENT = "comment"
    OTHER = "other"


class SyncStatus(StrEnum):
    """Status of a sync run."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class GitLabEvent(BaseModel):
    """A normalized activity event gathered from GitLab APIs."""

    source_id: str
    event_type: EventType
    title: str
    project_name: str
    timestamp: datetime
    url: str | None = None
    details: dict[str, str] = Field(default_factory=dict)

    @property
    def commit_message(self) -> str:
        """Render the GitHub commit message used for the mirrored contribution."""
        return f"[{self.event_type}] {self.project_name}: {self.title}"


class SyncRun(BaseModel):
    """Information about a single synchronization execution."""

    id: int | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: SyncStatus
    events_synced: int = 0
    error: str | None = None


class ActivityRecord(BaseModel):
    """Stored activity log entry."""

    id: int
    source_id: str
    event_type: EventType
    project_name: str
    title: str
    event_timestamp: datetime
    url: str | None = None
    sync_run_id: int | None = None
    github_sha: str | None = None
    created_at: datetime


class DayCount(BaseModel):
    """Daily activity count used by the dashboard."""

    date: str
    count: int


class DashboardSnapshot(BaseModel):
    """Dashboard data assembled for the web UI."""

    last_sync: SyncRun | None
    total_events: int
    recent_events: list[ActivityRecord]
    daily_activity: list[DayCount]


def deduplicate_events(events: list[GitLabEvent]) -> list[GitLabEvent]:
    """Deduplicate events by source id while preserving the newest variant."""
    ordered: OrderedDict[str, GitLabEvent] = OrderedDict()
    for event in sorted(events, key=lambda item: item.timestamp):
        ordered[event.source_id] = event
    return sorted(ordered.values(), key=lambda item: item.timestamp)


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)
