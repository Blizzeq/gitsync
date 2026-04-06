"""SQLite persistence layer for GitSync."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from gitsync.core.models import (
    ActivityRecord,
    DashboardSnapshot,
    DayCount,
    EventType,
    GitLabEvent,
    SyncRun,
    SyncStatus,
    utc_now,
)


class Storage:
    """Persist sync runs, mirrored activity and UI configuration."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser()

    async def initialize(self) -> None:
        """Initialize the SQLite schema if it does not exist yet."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as connection:
            await connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    events_synced INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    event_timestamp TEXT NOT NULL,
                    url TEXT,
                    sync_run_id INTEGER,
                    github_sha TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(sync_run_id) REFERENCES sync_runs(id)
                );

                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            await connection.commit()

    async def create_sync_run(self) -> SyncRun:
        """Insert a running sync row and return its model representation."""
        started_at = utc_now()
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                """
                INSERT INTO sync_runs (started_at, status, events_synced)
                VALUES (?, ?, 0)
                """,
                (started_at.isoformat(), SyncStatus.RUNNING),
            )
            await connection.commit()
            sync_run_id = cursor.lastrowid
        return SyncRun(id=sync_run_id, started_at=started_at, status=SyncStatus.RUNNING)

    async def finish_sync_run(
        self,
        sync_run_id: int,
        *,
        status: SyncStatus,
        events_synced: int,
        error: str | None = None,
    ) -> SyncRun:
        """Update a sync run when execution ends."""
        finished_at = utc_now()
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                "SELECT started_at FROM sync_runs WHERE id = ?",
                (sync_run_id,),
            )
            row = await cursor.fetchone()
            started_at = (
                datetime.fromisoformat(row[0]).astimezone(UTC)
                if row and row[0]
                else finished_at
            )
            await connection.execute(
                """
                UPDATE sync_runs
                SET finished_at = ?, status = ?, events_synced = ?, error = ?
                WHERE id = ?
                """,
                (finished_at.isoformat(), status, events_synced, error, sync_run_id),
            )
            await connection.commit()
        return SyncRun(
            id=sync_run_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            events_synced=events_synced,
            error=error,
        )

    async def get_last_sync_time(self) -> datetime | None:
        """Return the newest mirrored event timestamp."""
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                "SELECT MAX(event_timestamp) FROM activity_log"
            )
            row = await cursor.fetchone()
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(row[0]).astimezone(UTC)

    async def activity_exists(self, source_id: str) -> bool:
        """Check whether an event has already been mirrored."""
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM activity_log WHERE source_id = ? LIMIT 1",
                (source_id,),
            )
            row = await cursor.fetchone()
        return row is not None

    async def save_activity(
        self,
        event: GitLabEvent,
        *,
        sync_run_id: int,
        github_sha: str | None,
    ) -> None:
        """Persist a mirrored activity event."""
        created_at = utc_now().isoformat()
        async with aiosqlite.connect(self.db_path) as connection:
            await connection.execute(
                """
                INSERT OR IGNORE INTO activity_log (
                    source_id,
                    event_type,
                    project_name,
                    title,
                    event_timestamp,
                    url,
                    sync_run_id,
                    github_sha,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.source_id,
                    event.event_type,
                    event.project_name,
                    event.title,
                    event.timestamp.isoformat(),
                    event.url,
                    sync_run_id,
                    github_sha,
                    created_at,
                ),
            )
            await connection.commit()

    async def get_last_sync_run(self) -> SyncRun | None:
        """Return the newest sync run."""
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                """
                SELECT id, started_at, finished_at, status, events_synced, error
                FROM sync_runs
                ORDER BY id DESC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
        return self._row_to_sync_run(row) if row else None

    async def get_recent_sync_runs(self, limit: int = 10) -> list[SyncRun]:
        """Return recent sync runs ordered from newest to oldest."""
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                """
                SELECT id, started_at, finished_at, status, events_synced, error
                FROM sync_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_sync_run(row) for row in rows]

    async def get_activity_log(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        event_type: EventType | None = None,
        search: str | None = None,
    ) -> list[ActivityRecord]:
        """Return paginated activity rows with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if search:
            clauses.append("(project_name LIKE ? OR title LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        offset = (page - 1) * per_page
        query = f"""
            SELECT id, source_id, event_type, project_name, title, event_timestamp, url, sync_run_id, github_sha, created_at
            FROM activity_log
            {where_sql}
            ORDER BY event_timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(query, params)
            rows = await cursor.fetchall()
        return [self._row_to_activity(row) for row in rows]

    async def count_activity(
        self,
        *,
        event_type: EventType | None = None,
        search: str | None = None,
    ) -> int:
        """Count activity rows matching optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if search:
            clauses.append("(project_name LIKE ? OR title LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                f"SELECT COUNT(*) FROM activity_log {where_sql}",
                params,
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_dashboard_snapshot(self, *, days: int = 30) -> DashboardSnapshot:
        """Assemble dashboard metrics for the UI."""
        last_sync = await self.get_last_sync_run()
        recent_events = await self.get_activity_log(page=1, per_page=10)
        total_events = await self.count_activity()
        since = utc_now().date() - timedelta(days=days - 1)
        day_map = {
            (since + timedelta(days=index)).isoformat(): 0 for index in range(days)
        }
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute(
                """
                SELECT substr(event_timestamp, 1, 10) AS day, COUNT(*)
                FROM activity_log
                WHERE event_timestamp >= ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (datetime.combine(since, datetime.min.time(), tzinfo=UTC).isoformat(),),
            )
            rows = await cursor.fetchall()
        for day, count in rows:
            if day in day_map:
                day_map[day] = int(count)
        daily_activity = [
            DayCount(date=day, count=count) for day, count in day_map.items()
        ]
        return DashboardSnapshot(
            last_sync=last_sync,
            total_events=total_events,
            recent_events=recent_events,
            daily_activity=daily_activity,
        )

    async def save_config(self, values: dict[str, str]) -> None:
        """Persist UI-editable settings as key/value pairs."""
        async with aiosqlite.connect(self.db_path) as connection:
            for key, value in values.items():
                await connection.execute(
                    """
                    INSERT INTO config (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )
            await connection.commit()

    async def load_config(self) -> dict[str, str]:
        """Load persisted UI configuration values."""
        async with aiosqlite.connect(self.db_path) as connection:
            cursor = await connection.execute("SELECT key, value FROM config")
            rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    def _row_to_sync_run(row: Sequence[Any]) -> SyncRun:
        return SyncRun(
            id=int(row[0]),
            started_at=datetime.fromisoformat(row[1]).astimezone(UTC),
            finished_at=(
                datetime.fromisoformat(row[2]).astimezone(UTC) if row[2] else None
            ),
            status=SyncStatus(row[3]),
            events_synced=int(row[4]),
            error=row[5],
        )

    @staticmethod
    def _row_to_activity(row: Sequence[Any]) -> ActivityRecord:
        return ActivityRecord(
            id=int(row[0]),
            source_id=row[1],
            event_type=EventType(row[2]),
            project_name=row[3],
            title=row[4],
            event_timestamp=datetime.fromisoformat(row[5]).astimezone(UTC),
            url=row[6],
            sync_run_id=row[7],
            github_sha=row[8],
            created_at=datetime.fromisoformat(row[9]).astimezone(UTC),
        )
